"""최소 기능 CFB(OLE 복합 문서) 읽기/쓰기 — HWP5 파일 편집용.

외부 라이브러리 없이 동작합니다. 512바이트 섹터(버전 3) 파일만 지원합니다.
"""
import struct

FREE = 0xFFFFFFFF
ENDOFCHAIN = 0xFFFFFFFE
FATSECT = 0xFFFFFFFD
DIFSECT = 0xFFFFFFFC
NOSTREAM = 0xFFFFFFFF

SECTOR = 512
MINI_SECTOR = 64
MINI_CUTOFF = 4096


class Entry:
    def __init__(self):
        self.name = ""
        self.type = 0          # 1=storage, 2=stream, 5=root
        self.clsid = b"\x00" * 16
        self.state = 0
        self.ctime = b"\x00" * 8
        self.mtime = b"\x00" * 8
        self.children = []     # Entry 목록 (storage/root)
        self.data = b""        # stream 내용


def _cmp_key(name):
    # CFB 규칙: 이름 길이 먼저, 같으면 대문자 비교
    return (len(name), name.upper())


class CFB:
    def __init__(self):
        self.root = Entry()
        self.root.name = "Root Entry"
        self.root.type = 5

    # ---------------- 읽기 ----------------
    @classmethod
    def from_bytes(cls, d):
        if d[:8] != bytes.fromhex("d0cf11e0a1b11ae1"):
            raise ValueError("복합 문서(OLE) 파일이 아닙니다")
        major, = struct.unpack_from("<H", d, 0x1A)
        shift, mshift = struct.unpack_from("<HH", d, 0x1E)
        if major != 3 or shift != 9 or mshift != 6:
            raise ValueError("지원하지 않는 복합 문서 버전입니다")
        nfat, dirstart, _, cutoff, minifat, nminifat, difat, ndifat = \
            struct.unpack_from("<IIIIIIII", d, 0x2C)

        def sec(i):
            off = (i + 1) * SECTOR
            return d[off:off + SECTOR]

        # DIFAT -> FAT 섹터 목록
        fat_sectors = list(struct.unpack_from("<109I", d, 0x4C))
        nxt = difat
        for _ in range(ndifat):
            if nxt in (ENDOFCHAIN, FREE):
                break
            vals = struct.unpack("<128I", sec(nxt))
            fat_sectors += list(vals[:127])
            nxt = vals[127]
        fat_sectors = [s for s in fat_sectors if s not in (FREE, ENDOFCHAIN)][:nfat]
        fat = []
        for s in fat_sectors:
            fat += list(struct.unpack("<128I", sec(s)))

        def chain(start):
            out, seen = [], set()
            s = start
            while s not in (ENDOFCHAIN, FREE):
                if s in seen or s >= len(fat):
                    raise ValueError("FAT 체인 손상")
                seen.add(s)
                out.append(s)
                s = fat[s]
            return out

        def read_chain(start, size=None):
            buf = b"".join(sec(s) for s in chain(start))
            return buf if size is None else buf[:size]

        dir_bytes = read_chain(dirstart)
        raw = []
        for i in range(len(dir_bytes) // 128):
            e = dir_bytes[i * 128:(i + 1) * 128]
            nlen = struct.unpack_from("<H", e, 64)[0]
            name = e[:max(nlen - 2, 0)].decode("utf-16-le") if nlen else ""
            etype = e[66]
            left, right, child = struct.unpack_from("<III", e, 68)
            clsid = e[80:96]
            state = struct.unpack_from("<I", e, 96)[0]
            ctime, mtime = e[100:108], e[108:116]
            start = struct.unpack_from("<I", e, 116)[0]
            size = struct.unpack_from("<Q", e, 120)[0]
            raw.append((name, etype, left, right, child, clsid, state,
                        ctime, mtime, start, size))

        root_size = raw[0][10]
        mini_stream = read_chain(raw[0][9], root_size)
        minifat_vals = []
        if nminifat:
            mb = read_chain(minifat)
            minifat_vals = list(struct.unpack("<%dI" % (len(mb) // 4), mb))

        def read_mini(start, size):
            out, s, seen = [], start, set()
            while s not in (ENDOFCHAIN, FREE):
                if s in seen:
                    raise ValueError("미니 FAT 체인 손상")
                seen.add(s)
                out.append(mini_stream[s * MINI_SECTOR:(s + 1) * MINI_SECTOR])
                s = minifat_vals[s]
            return b"".join(out)[:size]

        def build(idx):
            (name, etype, left, right, child, clsid, state,
             ctime, mtime, start, size) = raw[idx]
            e = Entry()
            e.name, e.type, e.clsid, e.state = name, etype, clsid, state
            e.ctime, e.mtime = ctime, mtime
            if etype == 2:
                e.data = read_mini(start, size) if size < cutoff else read_chain(start, size)
            if child != NOSTREAM:
                stack, node, order = [], child, []
                while stack or node != NOSTREAM:
                    while node != NOSTREAM:
                        stack.append(node)
                        node = raw[node][2]
                    node = stack.pop()
                    order.append(node)
                    node = raw[node][3]
                e.children = [build(i) for i in order]
            return e

        c = cls()
        c.root = build(0)
        c.root.name = "Root Entry"
        return c

    # ---------------- 탐색/수정 ----------------
    def _find(self, path, create_parent=False):
        parts = path.split("/")
        cur = self.root
        for p in parts[:-1]:
            nxt = [c for c in cur.children if c.name == p and c.type == 1]
            if not nxt:
                raise KeyError(path)
            cur = nxt[0]
        return cur, parts[-1]

    def read(self, path):
        parent, leaf = self._find(path)
        for c in parent.children:
            if c.name == leaf and c.type == 2:
                return c.data
        raise KeyError(path)

    def write(self, path, data):
        parent, leaf = self._find(path)
        for c in parent.children:
            if c.name == leaf and c.type == 2:
                c.data = bytes(data)
                return
        raise KeyError(path)

    def remove(self, path):
        parent, leaf = self._find(path)
        parent.children = [c for c in parent.children if c.name != leaf]

    def list_streams(self):
        out = []

        def walk(e, prefix):
            for c in e.children:
                p = prefix + c.name
                if c.type == 2:
                    out.append(p)
                else:
                    walk(c, p + "/")
        walk(self.root, "")
        return out

    # ---------------- 쓰기 ----------------
    def to_bytes(self):
        # 1) 디렉터리 항목 번호 부여 (루트 = 0)
        order = []

        def collect(e):
            order.append(e)
            for c in e.children:
                collect(c)
        collect(self.root)
        ids = {id(e): i for i, e in enumerate(order)}

        # 2) 형제 노드를 균형 이진 트리로 연결 (모두 검정)
        links = {}  # id(entry) -> [left, right, child]

        def build_tree(nodes):
            if not nodes:
                return NOSTREAM
            nodes_sorted = sorted(nodes, key=lambda n: _cmp_key(n.name))

            def rec(lo, hi):
                if lo >= hi:
                    return NOSTREAM
                mid = (lo + hi) // 2
                n = nodes_sorted[mid]
                links[id(n)][0] = rec(lo, mid)
                links[id(n)][1] = rec(mid + 1, hi)
                return ids[id(n)]
            for n in nodes_sorted:
                links[id(n)] = [NOSTREAM, NOSTREAM, NOSTREAM]
            return rec(0, len(nodes_sorted))

        for e in order:
            links.setdefault(id(e), [NOSTREAM, NOSTREAM, NOSTREAM])
        for e in order:
            if e.children:
                for c in e.children:
                    links.setdefault(id(c), [NOSTREAM, NOSTREAM, NOSTREAM])
                links[id(e)][2] = build_tree(e.children)

        # 3) 스트림 배치
        mini_data = bytearray()
        minifat = []
        big = []  # (entry, data)
        start_of = {}
        for e in order[1:]:
            if e.type != 2:
                continue
            n = len(e.data)
            if n == 0:
                start_of[id(e)] = ENDOFCHAIN
            elif n < MINI_CUTOFF:
                first = len(minifat)
                cnt = (n + MINI_SECTOR - 1) // MINI_SECTOR
                for i in range(cnt):
                    minifat.append(first + i + 1 if i < cnt - 1 else ENDOFCHAIN)
                mini_data += e.data + b"\x00" * (cnt * MINI_SECTOR - n)
                start_of[id(e)] = first
            else:
                big.append(e)

        n_big = sum((len(e.data) + SECTOR - 1) // SECTOR for e in big)
        n_mini_cont = (len(mini_data) + SECTOR - 1) // SECTOR
        n_minifat = (len(minifat) * 4 + SECTOR - 1) // SECTOR
        n_dir = (len(order) + 3) // 4
        base = n_big + n_mini_cont + n_minifat + n_dir

        n_fat = 1
        while True:
            n_difat = 0 if n_fat <= 109 else ((n_fat - 109) + 126) // 127
            if (base + n_fat + n_difat) <= n_fat * 128:
                break
            n_fat += 1

        # 섹터 번호 할당
        cur = 0
        fat = [FREE] * (n_fat * 128)

        def alloc(count):
            nonlocal cur
            first = cur
            for i in range(count):
                fat[cur + i] = cur + i + 1 if i < count - 1 else ENDOFCHAIN
            cur += count
            return first

        sector_bytes = []  # (sector index, bytes)
        for e in big:
            cnt = (len(e.data) + SECTOR - 1) // SECTOR
            start_of[id(e)] = alloc(cnt)
            padded = e.data + b"\x00" * (cnt * SECTOR - len(e.data))
            sector_bytes.append((start_of[id(e)], padded))
        mini_cont_start = alloc(n_mini_cont) if n_mini_cont else ENDOFCHAIN
        if n_mini_cont:
            sector_bytes.append((mini_cont_start,
                                 bytes(mini_data) + b"\x00" * (n_mini_cont * SECTOR - len(mini_data))))
        minifat_start = alloc(n_minifat) if n_minifat else ENDOFCHAIN
        if n_minifat:
            mf = struct.pack("<%dI" % len(minifat), *minifat)
            mf += b"\xff" * (n_minifat * SECTOR - len(mf))
            sector_bytes.append((minifat_start, mf))
        dir_start = alloc(n_dir)
        dir_buf = bytearray()
        for e in order:
            raw = bytearray(128)
            nm = e.name.encode("utf-16-le")
            raw[0:len(nm)] = nm
            struct.pack_into("<H", raw, 64, len(nm) + 2)
            raw[66] = e.type
            raw[67] = 1  # 검정
            l, r, ch = links[id(e)]
            struct.pack_into("<III", raw, 68, l, r, ch)
            raw[80:96] = e.clsid
            struct.pack_into("<I", raw, 96, e.state)
            raw[100:108] = e.ctime
            raw[108:116] = e.mtime
            if e is self.root:
                start, size = mini_cont_start, len(mini_data)
            elif e.type == 2:
                start, size = start_of[id(e)], len(e.data)
            else:
                start, size = 0, 0
            struct.pack_into("<I", raw, 116, start)
            struct.pack_into("<Q", raw, 120, size)
            dir_buf += raw
        while len(dir_buf) < n_dir * SECTOR:
            empty = bytearray(128)
            struct.pack_into("<III", empty, 68, NOSTREAM, NOSTREAM, NOSTREAM)
            dir_buf += empty
        sector_bytes.append((dir_start, bytes(dir_buf)))

        fat_start = cur
        fat_ids = []
        for i in range(n_fat):
            fat[cur] = FATSECT
            fat_ids.append(cur)
            cur += 1
        difat_start = ENDOFCHAIN
        difat_ids = []
        for i in range(n_difat):
            fat[cur] = DIFSECT
            difat_ids.append(cur)
            cur += 1
        if n_difat:
            difat_start = difat_ids[0]

        # DIFAT 섹터 내용
        extra = fat_ids[109:]
        for i, sid in enumerate(difat_ids):
            chunk = extra[i * 127:(i + 1) * 127]
            vals = chunk + [FREE] * (127 - len(chunk))
            nxt = difat_ids[i + 1] if i + 1 < len(difat_ids) else ENDOFCHAIN
            sector_bytes.append((sid, struct.pack("<128I", *vals, nxt)))
        for i, sid in enumerate(fat_ids):
            sector_bytes.append((sid, struct.pack("<128I", *fat[i * 128:(i + 1) * 128])))

        header = bytearray(512)
        header[0:8] = bytes.fromhex("d0cf11e0a1b11ae1")
        struct.pack_into("<HHHHH", header, 0x18, 0x3E, 3, 0xFFFE, 9, 6)
        struct.pack_into("<I", header, 0x28, 0)
        struct.pack_into("<IIIIIIII", header, 0x2C, n_fat, dir_start, 0, MINI_CUTOFF,
                         minifat_start, n_minifat, difat_start, n_difat)
        first109 = fat_ids[:109] + [FREE] * (109 - len(fat_ids[:109]))
        struct.pack_into("<109I", header, 0x4C, *first109)

        out = bytearray(header)
        out += b"\x00" * (cur * SECTOR)
        for sid, data in sector_bytes:
            off = (sid + 1) * SECTOR
            out[off:off + len(data)] = data
        return bytes(out)
