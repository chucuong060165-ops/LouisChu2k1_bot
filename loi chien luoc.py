"""
LÕI CHIẾN LƯỢC — dùng chung cho phân tích trực tiếp (lay_du_lieu.py) và backtest (backtest.py),
để kết quả backtest phản ánh đúng quy tắc mà plugin dùng khi gợi ý lệnh thật.
Chỉ dùng thư viện có sẵn của Python.
"""
import json, random, time, urllib.request

TF_MS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
OKX_BAR = {"15m": "15m", "1h": "1H", "4h": "4H", "1d": "1Dutc"}

# ===== Thông số quy tắc (khớp references/chien-luoc.md) =====
QT = {
    "cham_vung_atr": 0.3,      # nến M15 chạm vùng nếu cách vùng <= 0.3×ATR H1
    "sl_qua_vung_atr": 0.1,    # SL cố định phải nằm ngoài vùng ít nhất 0.1×ATR H1
    "vol_xac_nhan": 1.2,       # volume nến xác nhận >= 1.2× TB20
    "vol_pha_vo": 1.5,         # phá vỡ thật cần volume >= 1.5× TB20
    "nen_qua_dai_atr": 2.5,    # nến dài > 2.5×ATR M15 = dễ hồi, không đuổi
    "phong_toi_thieu_R": 1.0,  # vùng cản phía trước phải cách >= 1R
    "so_nen_vung": 150,        # tìm vùng trong 150 nến H1 gần nhất
    "loc_d1": True,            # không đánh ngược xu hướng khung ngày
}


# ================= DỮ LIỆU =================
def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def _chuyen(k):
    return [int(k[0])] + [float(x) for x in k[1:6]]


KRAKEN_TF = {"15m": 15, "1h": 60, "4h": 240, "1d": 1440}


def lay_nen(symbol, tf, limit=300):
    """Nến gần nhất, cũ -> mới. Thử lần lượt: Binance, OKX, Kraken (Kraken dùng được cả ở máy chủ Mỹ)."""
    loi = []
    for base in ("https://data-api.binance.vision", "https://api.binance.com"):
        try:
            return [_chuyen(k) for k in _get(f"{base}/api/v3/klines?symbol={symbol}&interval={tf}&limit={limit}")], "Binance"
        except Exception as e:
            loi.append(f"{base}: {e}")
    try:
        inst = symbol[:-4] + "-USDT" if symbol.endswith("USDT") else symbol[:-3] + "-BTC"
        d = _get(f"https://www.okx.com/api/v5/market/candles?instId={inst}&bar={OKX_BAR[tf]}&limit={min(limit, 300)}")["data"]
        return [_chuyen(k) for k in d][::-1], "OKX"
    except Exception as e:
        loi.append(f"OKX: {e}")
    try:
        cap = symbol.replace("USDT", "USD").replace("BTC", "XBT")
        d = _get(f"https://api.kraken.com/0/public/OHLC?pair={cap}&interval={KRAKEN_TF[tf]}")
        if d.get("error"):
            raise RuntimeError(d["error"])
        key = [k for k in d["result"] if k != "last"][0]
        nen = [[int(k[0]) * 1000, float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[6])] for k in d["result"][key]]
        return nen[-limit:], "Kraken (giá USD)"
    except Exception as e:
        loi.append(f"Kraken: {e}")
    raise RuntimeError("Không lấy được dữ liệu: " + " | ".join(loi))


def chi_nen_da_dong(nen, tf, bay_gio_ms=None):
    """Chỉ giữ nến đã đóng hẳn (giờ mở + độ dài khung <= bây giờ). An toàn với mọi sàn."""
    t = bay_gio_ms if bay_gio_ms is not None else int(time.time() * 1000)
    return [x for x in nen if x[0] + TF_MS[tf] <= t]


def lay_lich_su(symbol, tf, so_ngay):
    """Lấy nhiều nến cho backtest (lật trang 1000 nến/lần)."""
    bat_dau = int(time.time() * 1000) - so_ngay * 86_400_000
    for base in ("https://api.binance.com", "https://data-api.binance.vision"):
        try:
            out, t = [], bat_dau
            while True:
                d = _get(f"{base}/api/v3/klines?symbol={symbol}&interval={tf}&startTime={t}&limit=1000")
                if not d:
                    break
                out += [_chuyen(k) for k in d]
                t = int(d[-1][0]) + TF_MS[tf]
                if len(d) < 1000:
                    break
                time.sleep(0.2)
            return out
        except Exception:
            continue
    raise RuntimeError(f"Không tải được lịch sử {symbol} {tf} từ Binance")


def du_lieu_demo(so_ngay=60, gia=3500.0, seed=7):
    """Dữ liệu giả (M15 rồi gộp thành H1/H4) để chạy thử khi không có mạng."""
    random.seed(seed)
    m15, t = [], 1_700_000_000_000 - (1_700_000_000_000 % TF_MS["4h"])
    for _ in range(so_ngay * 96):
        o = gia
        c = o * (1 + random.gauss(0, 0.0035))
        h = max(o, c) * (1 + abs(random.gauss(0, 0.0015)))
        l = min(o, c) * (1 - abs(random.gauss(0, 0.0015)))
        m15.append([t, o, h, l, c, random.uniform(200, 900) * (3 if random.random() < 0.05 else 1)])
        gia, t = c, t + TF_MS["15m"]

    def gop(n, step):
        out = []
        for i in range(0, len(m15) - n + 1, n):
            g = m15[i:i + n]
            out.append([g[0][0], g[0][1], max(x[2] for x in g), min(x[3] for x in g), g[-1][4], sum(x[5] for x in g)])
        return out
    return {"15m": m15, "1h": gop(4, TF_MS["1h"]), "4h": gop(16, TF_MS["4h"]), "1d": gop(96, TF_MS["1d"])}


# ================= CHỈ BÁO =================
def ema_ds(v, n):
    """EMA khởi tạo bằng SMA của n giá đầu (tránh sai lệch khi dữ liệu ngắn)."""
    if len(v) <= n:
        return [sum(v) / len(v)] * len(v)
    k = 2 / (n + 1)
    out = [sum(v[:n]) / n] * n
    for x in v[n:]:
        out.append(x * k + out[-1] * (1 - k))
    return out


def rsi_ds(c, n=14):
    out = [50.0] * len(c)
    if len(c) <= n:
        return out
    g = [max(c[i] - c[i - 1], 0) for i in range(1, len(c))]
    l = [max(c[i - 1] - c[i], 0) for i in range(1, len(c))]
    ag, al = sum(g[:n]) / n, sum(l[:n]) / n
    for i in range(n, len(g)):
        ag, al = (ag * (n - 1) + g[i]) / n, (al * (n - 1) + l[i]) / n
        out[i + 1] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def atr_ds(nen, n=14):
    out = [nen[0][2] - nen[0][3]] * len(nen)
    tr = [nen[0][2] - nen[0][3]] + [max(nen[i][2] - nen[i][3], abs(nen[i][2] - nen[i - 1][4]),
                                        abs(nen[i][3] - nen[i - 1][4])) for i in range(1, len(nen))]
    a = sum(tr[:n]) / n
    for i in range(n, len(nen)):
        a = (a * (n - 1) + tr[i]) / n
        out[i] = a
    return out


def vol_tb_ds(v, n=20):
    out = [v[0]] * len(v)
    for i in range(n, len(v)):
        out[i] = sum(v[i - n:i]) / n
    return out


def pivots(nen, k=3):
    """(chỉ số nến, giá, 'H'/'L', chỉ số khi pivot được XÁC NHẬN = i+k) — tránh nhìn trước tương lai."""
    out = []
    for i in range(k, len(nen) - k):
        cua_so = nen[i - k:i + k + 1]
        if nen[i][2] >= max(x[2] for x in cua_so):
            out.append((i, nen[i][2], "H", i + k))
        if nen[i][3] <= min(x[3] for x in cua_so):
            out.append((i, nen[i][3], "L", i + k))
    return out


def gom_vung(muc_gia, atr):
    """Gom mức giá gần nhau (<= 0.5×ATR) thành vùng: [(giá TB, số lần chạm)]."""
    cum = []
    for p in sorted(muc_gia):
        if cum and p - cum[-1][-1] <= 0.5 * atr:
            cum[-1].append(p)
        else:
            cum.append([p])
    return [(sum(c) / len(c), len(c)) for c in cum]


# ================= BỘ PHÂN TÍCH ĐA KHUNG =================
class BoPhanTich:
    """Tính sẵn chỉ báo cho 3 khung; danh_gia(j) xét nến M15 đã đóng thứ j."""

    def __init__(self, m15, h1, h4, d1=None):
        self.m15, self.h1, self.h4, self.d1 = m15, h1, h4, d1 or []
        cd = [x[4] for x in self.d1] or [0]
        self.e20_d, self.e50_d = ema_ds(cd, 20), ema_ds(cd, 50)
        self.id = -1
        c4 = [x[4] for x in h4]
        self.e20_4, self.e50_4, self.e200_4 = ema_ds(c4, 20), ema_ds(c4, 50), ema_ds(c4, 200)
        self.atr1 = atr_ds(h1)
        self.piv1 = pivots(h1)
        c15 = [x[4] for x in m15]
        self.rsi15 = rsi_ds(c15)
        self.atr15 = atr_ds(m15)
        self.vtb15 = vol_tb_ds([x[5] for x in m15])
        self.c1 = [x[4] for x in h1]
        self.rsi1 = rsi_ds(self.c1)
        self.i4 = self.i1 = -1

    def _chi_so_dong(self, nen, tro, t_dong, tf):
        """Chỉ số nến khung lớn cuối cùng đã ĐÓNG trước thời điểm t_dong."""
        while tro + 1 < len(nen) and nen[tro + 1][0] + TF_MS[tf] <= t_dong:
            tro += 1
        return tro

    def xu_huong_h4(self, i):
        if i < 200:
            return "CHƯA ĐỦ DỮ LIỆU"
        g, a, b = self.h4[i][4], self.e20_4[i], self.e50_4[i]
        if g > self.e200_4[i] and a > b:
            return "TĂNG"
        if g < self.e200_4[i] and a < b:
            return "GIẢM"
        return "ĐI NGANG"

    def xu_huong_d1(self, i):
        """Xu hướng khung ngày: giá so với EMA50 và EMA20/EMA50 của nến ngày đã đóng."""
        if i < 50:
            return "CHƯA RÕ"
        g, a, b = self.d1[i][4], self.e20_d[i], self.e50_d[i]
        if g > b and a > b:
            return "TĂNG"
        if g < b and a < b:
            return "GIẢM"
        return "ĐI NGANG"

    def vung_h1(self, i, gia):
        atr = self.atr1[i]
        if getattr(self, "_cache_i", None) != i:
            muc = [p for (idx, p, _, xn) in self.piv1 if xn <= i and idx >= i - QT["so_nen_vung"]]
            self._cache_i, self._cache_vung = i, gom_vung(muc, atr)
            self._cache_dinh = [(idx, pr) for (idx, pr, t, xn) in self.piv1 if t == "H" and xn <= i][-2:]
            self._cache_day = [(idx, pr) for (idx, pr, t, xn) in self.piv1 if t == "L" and xn <= i][-2:]
        vung = self._cache_vung
        tren = sorted([v for v in vung if v[0] > gia], key=lambda v: v[0])
        duoi = sorted([v for v in vung if v[0] <= gia], key=lambda v: -v[0])
        return tren, duoi, atr

    # ---------- Cảnh báo nhịp fake / nến fake ----------
    def canh_bao_fake(self, j, tren, duoi, atr1):
        cb, n, p = [], self.m15[j], self.m15[j - 1]
        o, h, l, c, v = n[1], n[2], n[3], n[4], n[5]
        than, bien = abs(c - o), max(h - l, 1e-9)
        vr = v / self.vtb15[j] if self.vtb15[j] else 1
        if h - max(o, c) > 2 * than and h - max(o, c) > 0.5 * bien:
            cb.append("Râu trên dài: bên bán từ chối giá, đừng long đuổi")
        if min(o, c) - l > 2 * than and min(o, c) - l > 0.5 * bien:
            cb.append("Râu dưới dài: bên mua đỡ giá, đừng short đuổi")
        if bien > QT["nen_qua_dai_atr"] * self.atr15[j]:
            cb.append(f"Nến M15 dài bất thường ({bien / self.atr15[j]:.1f}×ATR): dễ hồi lại, không đuổi")
        for g, _ in tren[:2]:
            if h > g and c < g:
                cb.append(f"Quét thanh khoản trên kháng cự {g:.2f} rồi đóng lại dưới: BẪY PHÁ VỠ LÊN (bull trap)")
        for g, _ in duoi[:2]:
            if l < g and c > g:
                cb.append(f"Quét thanh khoản dưới hỗ trợ {g:.2f} rồi đóng lại trên: BẪY PHÁ VỠ XUỐNG (bear trap)")
        # Quét đỉnh / đáy NGÀY hôm trước (vùng thanh khoản lớn nhất trong ngày)
        if self.id >= 0:
            pdh, pdl = self.d1[self.id][2], self.d1[self.id][3]
            if h > pdh and c < pdh:
                cb.append(f"Quét đỉnh ngày hôm trước {pdh:.2f} rồi đóng lại dưới: BẪY PHÁ VỠ LÊN (bull trap)")
            if l < pdl and c > pdl:
                cb.append(f"Quét đáy ngày hôm trước {pdl:.2f} rồi đóng lại trên: BẪY PHÁ VỠ XUỐNG (bear trap)")
        # Phá vỡ: vùng vừa bị vượt nằm giữa giá đóng nến trước và nến này
        for g, _ in tren[:2] + duoi[:2]:
            if p[4] < g < c and vr < QT["vol_pha_vo"]:
                cb.append(f"Vượt {g:.2f} nhưng volume chỉ {vr:.1f}×TB: phá vỡ yếu, dễ fake — chờ retest")
            if p[4] > g > c and vr < QT["vol_pha_vo"]:
                cb.append(f"Thủng {g:.2f} nhưng volume chỉ {vr:.1f}×TB: phá vỡ yếu, dễ fake — chờ retest")
        # Phân kỳ RSI trên H1 (2 đỉnh/đáy gần nhất)
        i1 = self.i1
        dinh, day = self._cache_dinh, self._cache_day
        if len(dinh) == 2 and dinh[1][1] > dinh[0][1] and self.rsi1[dinh[1][0]] < self.rsi1[dinh[0][0]]:
            cb.append("Phân kỳ giảm RSI H1: đỉnh giá cao hơn nhưng RSI yếu hơn — lực tăng đuối")
        if len(day) == 2 and day[1][1] < day[0][1] and self.rsi1[day[1][0]] > self.rsi1[day[0][0]]:
            cb.append("Phân kỳ tăng RSI H1: đáy giá thấp hơn nhưng RSI mạnh hơn — lực giảm đuối")
        return cb

    # ---------- Đánh giá tín hiệu ----------
    def danh_gia(self, j, sl, sl_atr=None):
        """sl: khoảng SL cố định (giá). sl_atr: nếu có, SL = sl_atr × ATR H1 (thay cho SL cố định)."""
        n, p = self.m15[j], self.m15[j - 1]
        t_dong = n[0] + TF_MS["15m"]
        self.i4 = self._chi_so_dong(self.h4, self.i4, t_dong, "4h")
        self.i1 = self._chi_so_dong(self.h1, self.i1, t_dong, "1h")
        if self.d1:
            self.id = self._chi_so_dong(self.d1, self.id, t_dong, "1d")
        kq = {"huong": None, "ly_do": [], "canh_bao": [], "so_xac_nhan": 0, "bias_d1": "KHÔNG CÓ"}
        if self.i4 < 200 or self.i1 < 30 or j < 30:
            kq["ly_do"].append("Chưa đủ dữ liệu")
            return kq
        bias = self.xu_huong_h4(self.i4)
        o, h, l, c, v = n[1], n[2], n[3], n[4], n[5]
        tren, duoi, atr1 = self.vung_h1(self.i1, c)
        if sl_atr:
            sl = sl_atr * atr1
        kq["sl"] = sl
        bias_d1 = self.xu_huong_d1(self.id) if self.d1 else "KHÔNG CÓ"
        pdh = self.d1[self.id][2] if self.d1 and self.id >= 0 else None
        pdl = self.d1[self.id][3] if self.d1 and self.id >= 0 else None
        kq.update(bias_h4=bias, bias_d1=bias_d1, pdh=pdh, pdl=pdl, ho_tro=duoi[:3], khang_cu=tren[:3], atr_h1=atr1)
        kq["canh_bao"] = self.canh_bao_fake(j, tren, duoi, atr1)

        bien = max(h - l, 1e-9)
        vr = v / self.vtb15[j] if self.vtb15[j] else 1
        r, r_truoc = self.rsi15[j], self.rsi15[j - 1]
        if bien > QT["nen_qua_dai_atr"] * self.atr15[j]:
            kq["ly_do"].append("Nến quá dài — không đuổi")
            return kq

        # LONG
        if bias == "TĂNG" and duoi:
            s = duoi[0][0]
            if l <= s + QT["cham_vung_atr"] * atr1 and c > s:
                xn = sum([
                    c > o and (min(o, c) - l >= 0.4 * bien or c > p[2]),
                    r_truoc < 40 <= r or (r > r_truoc and 35 <= r <= 60),
                    vr >= QT["vol_xac_nhan"],
                ])
                phong = min([g - c for g in ([tren[0][0]] if tren else []) + ([pdh] if pdh and pdh > c else [])] or [9e9])
                if bias_d1 == "GIẢM" and QT["loc_d1"]:
                    kq["ly_do"].append("H4 tăng nhưng khung NGÀY đang giảm — không đánh ngược khung lớn")
                elif c - sl >= s - QT["sl_qua_vung_atr"] * atr1:
                    kq["ly_do"].append("SL cố định nằm trong vùng hỗ trợ — dễ bị quét, bỏ")
                elif phong < QT["phong_toi_thieu_R"] * sl:
                    kq["ly_do"].append("Kháng cự / đỉnh ngày quá gần phía trên — không đủ chỗ chạy")
                elif xn >= 2:
                    kq["huong"], kq["so_xac_nhan"] = "LONG", xn
                    kq["ly_do"].append(f"Hồi về hỗ trợ {s:.2f} thuận xu hướng H4, {xn}/3 xác nhận M15")
                else:
                    kq["ly_do"].append(f"Chạm hỗ trợ nhưng mới {xn}/3 xác nhận M15 — chờ")
        # SHORT
        if bias == "GIẢM" and tren and kq["huong"] is None:
            k = tren[0][0]
            if h >= k - QT["cham_vung_atr"] * atr1 and c < k:
                xn = sum([
                    c < o and (h - max(o, c) >= 0.4 * bien or c < p[3]),
                    r_truoc > 60 >= r or (r < r_truoc and 40 <= r <= 65),
                    vr >= QT["vol_xac_nhan"],
                ])
                phong = min([c - g for g in ([duoi[0][0]] if duoi else []) + ([pdl] if pdl and pdl < c else [])] or [9e9])
                if bias_d1 == "TĂNG" and QT["loc_d1"]:
                    kq["ly_do"].append("H4 giảm nhưng khung NGÀY đang tăng — không đánh ngược khung lớn")
                elif c + sl <= k + QT["sl_qua_vung_atr"] * atr1:
                    kq["ly_do"].append("SL cố định nằm trong vùng kháng cự — dễ bị quét, bỏ")
                elif phong < QT["phong_toi_thieu_R"] * sl:
                    kq["ly_do"].append("Hỗ trợ / đáy ngày quá gần phía dưới — không đủ chỗ chạy")
                elif xn >= 2:
                    kq["huong"], kq["so_xac_nhan"] = "SHORT", xn
                    kq["ly_do"].append(f"Hồi lên kháng cự {k:.2f} thuận xu hướng H4, {xn}/3 xác nhận M15")
                else:
                    kq["ly_do"].append(f"Chạm kháng cự nhưng mới {xn}/3 xác nhận M15 — chờ")
        # Cảnh báo bẫy ngược hướng lệnh -> huỷ
        if kq["huong"] == "LONG" and any("BẪY PHÁ VỠ LÊN" in x or "Phân kỳ giảm" in x for x in kq["canh_bao"]):
            kq["ly_do"].append("Huỷ LONG vì có dấu hiệu bẫy/phân kỳ ngược hướng")
            kq["huong"] = None
        if kq["huong"] == "SHORT" and any("BẪY PHÁ VỠ XUỐNG" in x or "Phân kỳ tăng" in x for x in kq["canh_bao"]):
            kq["ly_do"].append("Huỷ SHORT vì có dấu hiệu bẫy/phân kỳ ngược hướng")
            kq["huong"] = None
        if not kq["ly_do"]:
            kq["ly_do"].append(f"H4 {bias}, giá chưa về vùng — chờ")
        return kq


# ================= TIỆN ÍCH =================
BUOC_KL = {"BTCUSDT": 0.0001, "ETHUSDT": 0.01}   # MEXC: 1 hợp đồng BTC = 0.0001, ETH = 0.01 (kiểm tra lại trên app)


def lam_tron_kl(coin, kl, buoc=None):
    """Làm tròn XUỐNG theo bước khối lượng của sàn (để không vượt rủi ro)."""
    b = buoc or BUOC_KL.get(coin, 0.001)
    return round(int(kl / b + 1e-9) * b, 6)


def xu_huong_nhanh(nen):
    """Xu hướng H1 đơn giản dùng để lọc theo BTC."""
    c = [x[4] for x in nen]
    e20, e50 = ema_ds(c, 20)[-1], ema_ds(c, 50)[-1]
    if c[-1] > e50 and e20 > e50:
        return "TĂNG"
    if c[-1] < e50 and e20 < e50:
        return "GIẢM"
    return "ĐI NGANG"


def lich_tin_lon():
    """Tin USD tác động mạnh tuần này (lịch Forex Factory, miễn phí).
    Trả về list (thời điểm có múi giờ, tên tin). Lỗi mạng -> list rỗng."""
    import datetime as _dt
    try:
        d = _get("https://nfs.faireconomy.media/ff_calendar_thisweek.json")
        out = []
        for e in d:
            if e.get("country") == "USD" and e.get("impact") == "High":
                try:
                    out.append((_dt.datetime.fromisoformat(e["date"]), e.get("title", "")))
                except Exception:
                    pass
        return out
    except Exception:
        return []


# ================= KHUNG GIỜ HAY CÓ NHỊP FAKE =================
# "gio": VN (UTC+7) | NY (New York, tự đổi giờ mùa hè/đông) | LON (London, tự đổi giờ)
# "che_do": "chan" = không báo kèo trong khung | "canh_bao" = vẫn báo nhưng kèm cảnh báo
KHUNG_GIO_MAC_DINH = [
    {"ten": "Sáng: mở nến ngày + funding (kinh nghiệm của bạn)", "tu": "07:00", "den": "08:30", "gio": "VN", "che_do": "chan"},
    {"ten": "Tối: tin Mỹ + mở cửa chứng khoán Mỹ (kinh nghiệm của bạn)", "tu": "08:30", "den": "10:00", "gio": "NY", "che_do": "chan"},
    {"ten": "Mở phiên Âu (hay phá vỡ giả)", "tu": "08:00", "den": "09:30", "gio": "LON", "che_do": "canh_bao"},
    {"ten": "Funding 15h/23h VN (hay giật râu)", "tu": "14:50", "den": "15:15", "gio": "VN", "che_do": "canh_bao"},
    {"ten": "Funding 15h/23h VN (hay giật râu)", "tu": "22:50", "den": "23:15", "gio": "VN", "che_do": "canh_bao"},
    {"ten": "Cuối tuần (thanh khoản mỏng)", "tu": "00:00", "den": "23:59", "gio": "VN", "thu": [5, 6], "che_do": "canh_bao"},
]


def _chu_nhat_thu_n(nam, thang, n):
    """Ngày Chủ nhật thứ n của tháng (n=-1: Chủ nhật cuối cùng)."""
    import datetime as _dt
    if n > 0:
        d = _dt.date(nam, thang, 1)
        d += _dt.timedelta(days=(6 - d.weekday()) % 7)
        return d + _dt.timedelta(weeks=n - 1)
    d = _dt.date(nam + (thang == 12), thang % 12 + 1, 1) - _dt.timedelta(days=1)
    return d - _dt.timedelta(days=(d.weekday() + 1) % 7)


def gio_dia_phuong(t_utc, vung):
    """Đổi thời điểm UTC sang giờ VN / New York / London (tự tính giờ mùa hè)."""
    import datetime as _dt
    if vung == "VN":
        return t_utc + _dt.timedelta(hours=7)
    y = t_utc.year
    if vung == "NY":   # mùa hè: Chủ nhật thứ 2 tháng 3 -> Chủ nhật đầu tháng 11
        bd = _dt.datetime.combine(_chu_nhat_thu_n(y, 3, 2), _dt.time(7), t_utc.tzinfo)
        kt = _dt.datetime.combine(_chu_nhat_thu_n(y, 11, 1), _dt.time(6), t_utc.tzinfo)
        return t_utc + _dt.timedelta(hours=-4 if bd <= t_utc < kt else -5)
    if vung == "LON":  # mùa hè: Chủ nhật cuối tháng 3 -> Chủ nhật cuối tháng 10
        bd = _dt.datetime.combine(_chu_nhat_thu_n(y, 3, -1), _dt.time(1), t_utc.tzinfo)
        kt = _dt.datetime.combine(_chu_nhat_thu_n(y, 10, -1), _dt.time(1), t_utc.tzinfo)
        return t_utc + _dt.timedelta(hours=1 if bd <= t_utc < kt else 0)
    return t_utc


def khung_gio_fake(t_ms, ds_khung=None):
    """Trả về khung giờ fake đang chứa thời điểm t_ms (hoặc None)."""
    import datetime as _dt
    t = _dt.datetime.fromtimestamp(t_ms / 1000, _dt.timezone.utc)
    for k in (KHUNG_GIO_MAC_DINH if ds_khung is None else ds_khung):
        dp = gio_dia_phuong(t, k.get("gio", "VN"))
        if "thu" in k and dp.weekday() not in k["thu"]:
            continue
        hm = dp.strftime("%H:%M")
        if (k["tu"] <= hm < k["den"]) if k["tu"] <= k["den"] else (hm >= k["tu"] or hm < k["den"]):
            return k
    return None


def ap_dung_khung_gio(kq, t_ms, ds_khung=None, chan=True):
    """Áp khung giờ fake vào kết quả đánh giá. chan=False: chỉ ghi nhận (dùng cho backtest so sánh)."""
    k = khung_gio_fake(t_ms, ds_khung)
    kq["khung_gio"] = k["ten"] if k else ""
    if not k or not kq.get("huong"):
        return kq
    if k["che_do"] == "chan" and chan:
        kq["ly_do"].append(f"Bỏ kèo vì đang trong khung giờ hay fake: {k['ten']}")
        kq["huong"] = None
    else:
        kq["canh_bao"].append(f"Đang trong khung giờ hay fake: {k['ten']} — chờ thêm 1 nến M15 xác nhận hoặc giảm nửa khối lượng")
    return kq


# ================= MÔ PHỎNG LỆNH (dùng chung cho backtest và theo dõi kèo của bot) =================
def tao_lenh(huong, gia, sl, rr, kl, phi=0.0005):
    d = 1 if huong == "LONG" else -1
    return {"huong": huong, "gia_vao": gia, "kl": kl, "sl": gia - d * sl, "sl_goc": gia - d * sl,
            "tp1": gia + d * sl, "tp2": gia + d * rr * sl, "da_tp1": False, "con_lai": 1.0,
            "lai_lo": 0.0, "phi": gia * kl * phi, "dien_bien": []}


def cap_nhat_lenh(mo, nen, phi=0.0005, truot=0.0, chot_tp1=0.5, mot_tp=False):
    """Đưa 1 nến vào lệnh đang mở. Trả về True nếu lệnh đã đóng hết.
    Cùng nến chạm SL và TP -> tính kết quả xấu (bi quan)."""
    L = mo["huong"] == "LONG"

    def dong(gia_ra, phan, ly_do):
        d = 1 if L else -1
        mo["lai_lo"] += d * (gia_ra - mo["gia_vao"]) * mo["kl"] * phan
        mo["phi"] += gia_ra * mo["kl"] * phan * phi
        mo["con_lai"] -= phan
        mo["dien_bien"].append(ly_do)

    hi, lo = nen[2], nen[3]
    if (lo <= mo["sl"]) if L else (hi >= mo["sl"]):
        gia_sl = mo["sl"] if mo["da_tp1"] else mo["sl"] * (1 - truot if L else 1 + truot)
        dong(gia_sl, mo["con_lai"], "về entry" if mo["da_tp1"] else "dính SL")
    else:
        if not mo["da_tp1"] and ((hi >= mo["tp1"]) if L else (lo <= mo["tp1"])):
            mo["da_tp1"] = True
            if not mot_tp:
                dong(mo["tp1"], chot_tp1, "TP1")
                mo["sl"] = mo["gia_vao"]
        if mo["con_lai"] > 1e-9 and ((hi >= mo["tp2"]) if L else (lo <= mo["tp2"])):
            dong(mo["tp2"], mo["con_lai"], "TP2")
    return mo["con_lai"] <= 1e-9


def dong_cuong_buc(mo, gia, phi=0.0005, ly_do="hết hạn"):
    d = 1 if mo["huong"] == "LONG" else -1
    mo["lai_lo"] += d * (gia - mo["gia_vao"]) * mo["kl"] * mo["con_lai"]
    mo["phi"] += gia * mo["kl"] * mo["con_lai"] * phi
    mo["con_lai"] = 0
    mo["dien_bien"].append(ly_do)


# ================= ETH/BTC & BTC DOMINANCE =================
def xu_huong_cap_ds(nen):
    """Xu hướng từng nến của một cặp (dùng cho ETH/BTC H4): giá so với EMA50 và EMA20/EMA50."""
    c = [x[4] for x in nen]
    e20, e50 = ema_ds(c, 20), ema_ds(c, 50)
    return ["TĂNG" if c[i] > e50[i] and e20[i] > e50[i] else "GIẢM" if c[i] < e50[i] and e20[i] < e50[i]
            else "ĐI NGANG" for i in range(len(c))]


class TheoDoiCap:
    """Tra xu hướng ETH/BTC H4 tại một thời điểm (chỉ dùng nến đã đóng)."""
    def __init__(self, nen_h4, tf="4h"):
        self.nen, self.xh, self.tf, self.i = nen_h4, xu_huong_cap_ds(nen_h4) if nen_h4 else [], tf, -1

    def tai(self, t_ms):
        while self.i + 1 < len(self.nen) and self.nen[self.i + 1][0] + TF_MS[self.tf] <= t_ms:
            self.i += 1
        return self.xh[self.i] if self.i >= 50 else None

    def thay_doi_24h(self):
        """% thay đổi ETH/BTC trong 24 giờ (6 nến H4 đã đóng)."""
        if self.i < 6:
            return None
        return (self.nen[self.i][4] / self.nen[self.i - 6][4] - 1) * 100


def ap_dung_eth_btc(kq, coin, xh, che_do="chan"):
    """Kinh nghiệm: BTC hút dom (ETH/BTC giảm) -> ETH yếu hơn, BTC sập thì ETH sập mạnh hơn.
    che_do: "chan" = bỏ LONG ETH khi ETH/BTC giảm | "canh_bao" = chỉ cảnh báo | "tat" = bỏ qua."""
    kq["ethbtc"] = xh if (coin == "ETHUSDT" and xh) else ""
    if coin != "ETHUSDT" or not xh or che_do == "tat" or not kq.get("huong"):
        return kq
    if kq["huong"] == "LONG" and xh == "GIẢM":
        if che_do == "chan":
            kq["ly_do"].append("Bỏ LONG ETH: ETH/BTC H4 đang giảm (BTC hút dom, ETH yếu hơn BTC)")
            kq["huong"] = None
        else:
            kq["canh_bao"].append("ETH/BTC H4 đang giảm (BTC hút dom) — LONG ETH là ngược dòng tiền")
    elif kq["huong"] == "SHORT" and xh == "TĂNG":
        kq["canh_bao"].append("ETH/BTC H4 đang tăng — ETH đang khỏe hơn BTC, SHORT ETH dễ bị kéo ngược")
    elif kq["huong"] == "SHORT" and xh == "GIẢM":
        kq["ly_do"].append("thuận dòng tiền: ETH/BTC giảm, ETH yếu hơn BTC")
    return kq


def lay_btc_dom():
    """% BTC dominance hiện tại (CoinGecko, miễn phí). Lỗi -> None."""
    try:
        return float(_get("https://api.coingecko.com/api/v3/global")["data"]["market_cap_percentage"]["btc"])
    except Exception:
        return None
