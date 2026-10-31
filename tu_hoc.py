#!/usr/bin/env python3
"""
TỰ HỌC TỪ LỊCH SỬ LỆNH — dùng chung cho bot Telegram và plugin /trading.

Ý tưởng: mỗi kèo được gắn "đặc điểm" (coin, hướng, khung giờ, xu hướng ngày, số xác nhận,
có cảnh báo fake hay không...). Sau khi có đủ lệnh, đặc điểm nào thường lỗ thì đề xuất CHẶN,
đặc điểm nào thường lãi thì đề xuất ƯU TIÊN. Không tự đổi quy tắc khi bạn chưa đồng ý.

Chạy trên máy (plugin):  python tu_hoc.py lich_su.csv [nhat-ky-trading.csv ...]
                         python tu_hoc.py https://raw.githubusercontent.com/<tên>/keo-bot/main/lich_su.csv
"""
import csv, io, sys, urllib.request

SO_LENH_TOI_THIEU = 15     # dưới mức này chưa đủ để kết luận
NGUONG_CHAN = -0.25        # kỳ vọng R thấp hơn -> đề xuất chặn
NGUONG_UU_TIEN = 0.30      # kỳ vọng R cao hơn -> đề xuất ưu tiên
CHENH_LECH = 0.30          # nhóm phải tệ/tốt hơn trung bình chung ít nhất ngần này

COT_LICH_SU = ["id", "nguon", "da_vao", "coin", "huong", "vao_luc", "gia_vao", "sl", "tp1", "tp2", "kl",
               "khung_gio", "bias_d1", "ethbtc", "so_xac_nhan", "canh_bao", "trang_thai", "dien_bien",
               "dong_luc", "R_mo_phong", "usdt_mo_phong", "ket_qua_thuc_usdt", "R"]


def so(x, mac_dinh=None):
    try:
        return float(str(x).replace(",", "."))
    except (TypeError, ValueError):
        return mac_dinh


def dac_trung(d):
    """Danh sách đặc điểm của 1 kèo (dạng chữ dễ đọc)."""
    out = [f"Coin {d.get('coin', '?').replace('USDT', '')}", f"Hướng {d.get('huong', '?')}"]
    gio = str(d.get("vao_luc", ""))[11:13]
    if gio.isdigit():
        g = int(gio) // 4 * 4
        out.append(f"Giờ vào {g:02d}h–{g + 4:02d}h VN")
    out.append(f"Khung fake: {d['khung_gio']}" if d.get("khung_gio") else "Ngoài khung giờ fake")
    if d.get("bias_d1") and d["bias_d1"] != "KHÔNG CÓ":
        out.append(f"Khung ngày {d['bias_d1']}")
    if d.get("ethbtc"):
        out.append(f"ETH/BTC H4 {d['ethbtc']}")
    if str(d.get("so_xac_nhan", "")) in ("2", "3"):
        out.append(f"{d['so_xac_nhan']}/3 xác nhận M15")
    cb = [x for x in str(d.get("canh_bao") or "").split(" | ") if x.strip() and not x.startswith("Đang trong khung giờ")]
    out.append("Có cảnh báo fake lúc vào" if cb else "Không cảnh báo fake lúc vào")
    return out


def doc_csv(nguon):
    if str(nguon).startswith("http"):
        with urllib.request.urlopen(nguon, timeout=20) as r:
            txt = r.read().decode("utf-8-sig")
    else:
        with open(nguon, encoding="utf-8-sig") as f:
            txt = f.read()
    return list(csv.DictReader(io.StringIO(txt)))


def lenh_da_xong(rows):
    """Chỉ lấy lệnh đã đóng, có R (ưu tiên kết quả thật bạn báo)."""
    return [r for r in rows if r.get("trang_thai") == "ĐÓNG" and so(r.get("R")) is not None]


def thong_ke(rows):
    nhom = {}
    for r in rows:
        for f in dac_trung(r):
            nhom.setdefault(f, []).append(so(r["R"]))
    return {f: {"n": len(v), "ky_vong": sum(v) / len(v), "thang": sum(x > 0.2 for x in v) / len(v)}
            for f, v in nhom.items()}


def goi_y(rows):
    """Đề xuất chặn / ưu tiên. Chỉ xét nhóm đủ số lệnh VÀ khác hẳn mức trung bình chung
    (để không chặn bừa khi cả chiến lược đang lỗ hoặc đang lãi)."""
    if not rows:
        return [], []
    tb = sum(so(r["R"]) for r in rows) / len(rows)
    tk = thong_ke(rows)
    chan = [(f, s) for f, s in tk.items() if s["n"] >= SO_LENH_TOI_THIEU and s["ky_vong"] <= NGUONG_CHAN
            and s["ky_vong"] <= tb - CHENH_LECH and s["n"] <= 0.7 * len(rows)
            and not f.startswith("Coin") and not f.startswith("Hướng")]
    uu = [(f, s) for f, s in tk.items() if s["n"] >= SO_LENH_TOI_THIEU and s["ky_vong"] >= NGUONG_UU_TIEN
          and s["ky_vong"] >= tb + CHENH_LECH]
    return sorted(chan, key=lambda x: x[1]["ky_vong"]), sorted(uu, key=lambda x: -x[1]["ky_vong"])


def bao_cao(rows, ngan=False):
    xong = lenh_da_xong(rows)
    if not xong:
        return "Chưa có lệnh nào đã đóng để học."
    R = [so(r["R"]) for r in xong]
    thuc = [r for r in xong if so(r.get("ket_qua_thuc_usdt")) is not None]
    dong = [f"📚 TỰ HỌC — {len(xong)} lệnh đã đóng ({len(thuc)} lệnh có kết quả thật bạn báo)",
            f"Tỷ lệ thắng {100 * sum(x > 0.2 for x in R) / len(R):.0f}% | kỳ vọng {sum(R) / len(R):+.2f}R/lệnh"]
    if thuc:
        dong.append(f"Lãi/lỗ thật đã báo: {sum(so(r['ket_qua_thuc_usdt']) for r in thuc):+.2f}u")
    tk = thong_ke(xong)
    if not ngan:
        dong.append("\nTheo từng đặc điểm (số lệnh | kỳ vọng):")
        for f, s in sorted(tk.items(), key=lambda x: x[1]["ky_vong"]):
            dau = "🔴" if s["ky_vong"] < -0.1 else "🟢" if s["ky_vong"] > 0.1 else "⚪"
            dong.append(f"{dau} {f}: {s['n']} | {s['ky_vong']:+.2f}R")
    chan, uu = goi_y(xong)
    tb = sum(R) / len(R)
    if len(xong) >= 30 and tb < -0.1:
        dong.append(f"\n⚠️ Toàn bộ quy tắc đang lỗ ({tb:+.2f}R/lệnh). Chặn từng nhóm KHÔNG cứu được — "
                    "cần xem lại quy tắc gốc (SL, điểm vào, khung thời gian) hoặc tạm dừng đánh thật.")
    if len(xong) < SO_LENH_TOI_THIEU:
        dong.append(f"\n⏳ Cần ít nhất {SO_LENH_TOI_THIEU} lệnh mỗi nhóm mới đề xuất thay đổi. Cứ tiếp tục ghi kết quả.")
    if chan:
        dong.append("\n⛔ Đề xuất CHẶN (thường lỗ):")
        dong += [f"• {f} — {s['n']} lệnh, {s['ky_vong']:+.2f}R" for f, s in chan]
    if uu:
        dong.append("\n✅ Nhóm đang hiệu quả (ưu tiên):")
        dong += [f"• {f} — {s['n']} lệnh, {s['ky_vong']:+.2f}R" for f, s in uu]
    if chan or uu:
        dong.append("\nLưu ý: mẫu nhỏ dễ đánh lừa. Chỉ chặn khi nhóm đó lỗ đều qua nhiều tuần.")
    return "\n".join(dong)


def ghi_chu_sau_lenh(lenh, rows):
    """Gợi ý ngắn sau khi 1 lệnh đóng: lệnh này rơi vào nhóm tốt hay xấu."""
    xong = lenh_da_xong(rows)
    tk = thong_ke(xong)
    R = so(lenh.get("R"), 0)
    y = []
    if R < 0 and "Có cảnh báo fake lúc vào" in dac_trung(lenh):
        y.append("Lúc vào lệnh đã có cảnh báo fake — lần sau cân nhắc bỏ qua hoặc giảm khối lượng.")
    if R < 0 and lenh.get("khung_gio"):
        y.append(f"Lệnh vào trong khung giờ hay fake ({lenh['khung_gio']}).")
    xau = [(f, tk[f]) for f in dac_trung(lenh) if f in tk and tk[f]["n"] >= 5 and tk[f]["ky_vong"] < -0.1]
    tot = [(f, tk[f]) for f in dac_trung(lenh) if f in tk and tk[f]["n"] >= 5 and tk[f]["ky_vong"] > 0.1]
    if xau:
        f, s = min(xau, key=lambda x: x[1]["ky_vong"])
        y.append(f"Nhóm yếu nhất của kèo này: {f} ({s['n']} lệnh, {s['ky_vong']:+.2f}R).")
    if tot and R > 0:
        f, s = max(tot, key=lambda x: x[1]["ky_vong"])
        y.append(f"Kèo thuộc nhóm đang hiệu quả: {f} ({s['n']} lệnh, {s['ky_vong']:+.2f}R).")
    if not y:
        y.append("Chưa đủ dữ liệu để rút bài học riêng cho kèo này — tiếp tục ghi kết quả.")
    return "💡 " + " ".join(y)


def bi_chan_boi(kq_dac_trung, bo_loc):
    """Kèo mới có trùng đặc điểm đã bị bạn đồng ý chặn không."""
    for f in kq_dac_trung:
        if f in bo_loc:
            return f
    return None


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Cách dùng: python tu_hoc.py <file csv hoặc link> [file khác ...]")
    rows = []
    for n in sys.argv[1:]:
        try:
            rows += doc_csv(n)
        except Exception as e:
            print(f"Không đọc được {n}: {e}")
    print(bao_cao(rows))
