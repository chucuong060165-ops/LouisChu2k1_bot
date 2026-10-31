#!/usr/bin/env python3
"""
BOT BÁO KÈO V3.2 — chạy mỗi 5 phút trên GitHub Actions, xét mỗi nến M15 vừa đóng. Dùng ĐÚNG quy tắc của plugin /trading.
Bạn KHÔNG cần sửa file này. Chỉ sửa cau_hinh.json. Token & chat ID nằm trong GitHub Secrets.

Lệnh nhắn cho bot (bot đọc mỗi ~5 phút):
  /kiemtra          phân tích ngay ETH, BTC
  /kq 12 +3.5       báo kết quả thật kèo #12 (lãi 3.5u). /kq -2.5 = kèo gần nhất lỗ 2.5u
  /bo 12            kèo #12 bạn KHÔNG vào (không tính vào số lệnh thua)
  /lichsu           10 kèo gần nhất
  /hoc              báo cáo tự học + đề xuất
  /apdung           đồng ý chặn các nhóm hay lỗ mà bot đề xuất  |  /bohoc  bỏ hết bộ lọc tự học
  /tinlon           lịch tin lớn tuần này
  /trangthai        tình hình hôm nay  |  /tat  /bat  tắt/bật báo kèo
"""
import csv, datetime as dt, json, os, re, sys, urllib.parse, urllib.request
from loi_chien_luoc import (BoPhanTich, lay_nen, du_lieu_demo, lam_tron_kl, xu_huong_nhanh, lich_tin_lon,
                            ap_dung_khung_gio, tao_lenh, cap_nhat_lenh, dong_cuong_buc, TF_MS, KHUNG_GIO_MAC_DINH,
                            TheoDoiCap, ap_dung_eth_btc, lay_btc_dom, chi_nen_da_dong)
import tu_hoc

VN = dt.timezone(dt.timedelta(hours=7))
THU_MUC = os.path.dirname(os.path.abspath(__file__))
FILE_TT = os.path.join(THU_MUC, "trang_thai.json")
FILE_LS = os.path.join(THU_MUC, "lich_su.csv")
TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT = str(os.environ.get("TELEGRAM_CHAT_ID", ""))
DEMO = os.environ.get("DEMO") == "1"


def bay_gio():
    return dt.datetime.now(VN)


def gio(ms=None, fmt="%d/%m %H:%M"):
    t = bay_gio() if ms is None else dt.datetime.fromtimestamp(ms / 1000, VN)
    return t.strftime(fmt)


def fg(x):
    return f"{x:,.2f}" if x < 10_000 else f"{x:,.0f}"


# ---------------- Telegram ----------------
def tg(method, **params):
    if DEMO:
        if method == "sendMessage":
            print("\n📩 " + params["text"])
        return {"result": []}
    req = urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/{method}",
                                 data=urllib.parse.urlencode(params).encode())
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def gui(text):
    for i in range(0, len(text), 3900):   # Telegram giới hạn ~4096 ký tự/tin
        try:
            tg("sendMessage", chat_id=CHAT, text=text[i:i + 3900], disable_web_page_preview="true")
        except Exception as e:
            print("Lỗi gửi Telegram:", e)


# ---------------- Lưu trữ ----------------
def doc_json(p, mac_dinh):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return mac_dinh


def doc_lich_su():
    try:
        with open(FILE_LS, encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))
    except Exception:
        return []


def ghi_lich_su(rows):
    with open(FILE_LS, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=tu_hoc.COT_LICH_SU, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


# ---------------- Tin lớn ----------------
def cap_nhat_lich_tin(tt):
    if DEMO:
        return
    lan_cuoi = tt.get("lich_tin_luc")
    if lan_cuoi and (bay_gio() - dt.datetime.fromisoformat(lan_cuoi)).total_seconds() < 6 * 3600:
        return
    tin = lich_tin_lon()
    if tin:
        tt["lich_tin"] = [[t.astimezone(VN).strftime("%Y-%m-%d %H:%M"), ten] for t, ten in tin]
        tt["lich_tin_luc"] = bay_gio().isoformat()


def ds_tin(ch, tt):
    out = [[s, "Tin bạn tự thêm"] for s in ch.get("tin_lon_gio_vn", [])] + tt.get("lich_tin", [])
    kq = []
    for s, ten in out:
        try:
            kq.append((dt.datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=VN), ten))
        except ValueError:
            pass
    return sorted(kq)


def nhac_tin(ch, tt):
    bn, h_tranh = bay_gio(), ch.get("tranh_tin_lon_gio", 2)
    da = tt.setdefault("da_nhac", {})
    for h in sorted(ch.get("nhac_tin_truoc_gio", [24, 1]), reverse=True):
        moi = [(t, ten) for t, ten in ds_tin(ch, tt)
               if 0 < (t - bn).total_seconds() <= h * 3600 and f"{h}|{t:%Y-%m-%d %H:%M}|{ten}" not in da]
        if not moi:
            continue
        for t, ten in moi:
            da[f"{h}|{t:%Y-%m-%d %H:%M}|{ten}"] = bn.isoformat()
        nhom = {}
        for t, ten in moi:
            nhom.setdefault(t, []).append(ten)
        dong = [("📅 TIN LỚN TRONG 24 GIỜ TỚI" if h >= 24 else f"⏰ CÒN KHOẢNG {h} GIỜ NỮA CÓ TIN LỚN") + " (giờ VN):"]
        for t, tens in nhom.items():
            dong.append(f"• {t:%a %d/%m %H:%M} — {', '.join(tens)}")
            dong.append(f"   Bot tự ĐỨNG NGOÀI từ {t - dt.timedelta(hours=h_tranh):%H:%M} đến {t + dt.timedelta(hours=h_tranh):%H:%M}.")
        dong.append("👉 Đang có lệnh: dời SL về entry hoặc chốt bớt trước giờ tin. Đừng mở lệnh mới sát giờ tin.")
        gui("\n".join(dong))
    for k in list(da):  # dọn mục cũ
        if (bn - dt.datetime.fromisoformat(da[k])).days > 8:
            del da[k]


def dang_gan_tin(ch, tt):
    bn = bay_gio()
    for t, ten in ds_tin(ch, tt):
        if abs((bn - t).total_seconds()) <= ch.get("tranh_tin_lon_gio", 2) * 3600:
            return f"{t:%d/%m %H:%M} {ten}"
    return None


# ---------------- Phân tích ----------------
def lay_du_lieu(coin):
    if DEMO:
        d = du_lieu_demo(150, 2240 if "ETH" in coin else 77400, seed=sum(map(ord, coin)))
        return {k: v[-501:] for k, v in d.items()}, "DEMO"
    data, nguon = {}, None
    for tf in ("15m", "1h", "4h", "1d"):
        data[tf], nguon = lay_nen(coin, tf, 500 if tf != "1d" else 200)
    return data, nguon


def phan_tich(coin, data, nguon, ch, dong_tien=None, da_xet_den=None):
    """Xét nến M15 đã đóng. Nếu GitHub chạy trễ làm sót nến, xét bù tối đa 3 nến gần nhất,
    nhưng chỉ dùng tín hiệu cũ khi giá hiện tại vẫn sát điểm vào và chưa chạm SL/TP1."""
    bn_ms = int(bay_gio().timestamp() * 1000)
    data = {k: chi_nen_da_dong(v, k, bn_ms) for k, v in data.items()}
    m15 = data["15m"]
    bo = BoPhanTich(m15, data["1h"], data["4h"], data["1d"])
    cuoi = len(m15) - 1
    ds_j = [j for j in range(max(30, cuoi - 2), cuoi + 1) if da_xet_den is None or m15[j][0] > da_xet_den] or [cuoi]
    if ds_j[0] != cuoi and da_xet_den is None:
        ds_j = [cuoi]
    dt_ = dong_tien or {}
    tin_hieu, kq = None, None
    for j in ds_j:
        kq = bo.danh_gia(j, ch["sl_co_dinh"][coin], ch.get("sl_theo_atr") or None)
        kq.update(gia=m15[j][4], t_nen=m15[j][0], nguon=nguon)
        ap_dung_khung_gio(kq, kq["t_nen"] + TF_MS["15m"], ch.get("khung_gio_fake", KHUNG_GIO_MAC_DINH))
        xh = dt_["ethbtc"].tai(kq["t_nen"] + TF_MS["15m"]) if dt_.get("ethbtc") else None
        ap_dung_eth_btc(kq, coin, xh, ch.get("loc_eth_btc", "chan"))
        kq["dong_tien_txt"] = mo_ta_dong_tien(coin, dt_, xh)
        if kq["huong"]:
            tin_hieu = (j, kq)
    if tin_hieu and tin_hieu[0] != cuoi and not kq["huong"]:
        j, k = tin_hieu
        sl, L = k["sl"], k["huong"] == "LONG"
        sau = m15[j + 1:]
        cham = any((n[3] <= k["gia"] - sl or n[2] >= k["gia"] + sl) if L else (n[2] >= k["gia"] + sl or n[3] <= k["gia"] - sl) for n in sau)
        if not cham and abs(m15[cuoi][4] - k["gia"]) <= 0.3 * sl:
            tre = (m15[cuoi][0] - k["t_nen"]) // 60000
            k["ly_do"].append(f"tín hiệu từ nến {tre} phút trước, giá vẫn sát điểm vào nên vào theo giá hiện tại")
            k.update(gia=m15[cuoi][4], t_nen=m15[cuoi][0])
            return k
    return kq


def mo_ta_dong_tien(coin, dt_, xh):
    phan = []
    if coin == "ETHUSDT" and xh:
        tdoi = dt_["ethbtc"].thay_doi_24h()
        phan.append(f"ETH/BTC H4 {xh}" + (f" ({tdoi:+.1f}%/24h)" if tdoi is not None else ""))
    if dt_.get("dom") is not None:
        phan.append(f"BTC.D {dt_['dom']:.1f}%" + (f" ({dt_['dom_24h']:+.2f}/24h)" if dt_.get("dom_24h") is not None else ""))
    return " | ".join(phan)


def cap_nhat_dom(tt):
    """Lưu BTC dominance mỗi giờ để biết dom đang được hút hay xả."""
    ds = tt.setdefault("dom", [])
    bn = bay_gio()
    if not DEMO and (not ds or (bn - dt.datetime.fromisoformat(ds[-1][0])).total_seconds() >= 3300):
        v = lay_btc_dom()
        if v is not None:
            ds.append([bn.isoformat(), round(v, 3)])
            del ds[:-200]
    if not ds:
        return None, None
    cu = [x for x in ds if (bn - dt.datetime.fromisoformat(x[0])).total_seconds() >= 23 * 3600]
    return ds[-1][1], (ds[-1][1] - cu[-1][1]) if cu else None


def tin_keo(id_, coin, kq, ch, kl, rui_ro):
    L = kq["huong"] == "LONG"
    d = 1 if L else -1
    gia, sl, rr = kq["gia"], kq["sl"], ch["rr"]
    phi = ch.get("phi_moi_chieu_phan_tram", 0.05) / 100
    cb = "\n".join("⚠️ " + x for x in kq["canh_bao"]) or "✅ Không thấy dấu hiệu fake"
    vung = (kq["ho_tro"] if L else kq["khang_cu"])[0][0]
    return (f"{'🟢 LONG' if L else '🔴 SHORT'} {coin} — kèo #{id_} — {fg(gia)}  ({gio(kq['t_nen'] + TF_MS['15m'])})\n"
            f"Ngày {kq['bias_d1']} | H4 {kq['bias_h4']} | {kq['so_xac_nhan']}/3 xác nhận M15\n"
            + (f"Dòng tiền: {kq['dong_tien_txt']}\n" if kq.get('dong_tien_txt') else "") +
            f"{'; '.join(kq['ly_do'])}\n\n"
            f"Vào: {fg(gia)}\nSL: {fg(gia - d * sl)}  (-{fg(sl)} giá)\n"
            f"TP1: {fg(gia + d * sl)}  (1R, chốt 1/2, dời SL về entry)\nTP2: {fg(gia + d * rr * sl)}  ({rr:g}R)\n"
            f"Khối lượng: {kl:g} {coin.replace('USDT', '')} (~{kl * gia:,.0f}u) — lỗ tối đa {rui_ro:g}u, phí ~{kl * gia * phi * 2:.2f}u\n\n"
            f"{cb}\n\n👉 Kèo hỏng nếu nến M15 đóng {'dưới' if L else 'trên'} {fg(vung)}. Mở chart kiểm tra trước khi vào.\n"
            f"Xong lệnh gõ /kq {id_} +lãi hoặc -lỗ (USDT). Không vào thì gõ /bo {id_}.\n"
            f"Nguồn giá: {kq['nguon']}. Không phải lời khuyên tài chính.")


def tom_tat(coin, kq):
    ht = ", ".join(fg(g) for g, _ in kq.get("ho_tro", [])[:2]) or "-"
    kc = ", ".join(fg(g) for g, _ in kq.get("khang_cu", [])[:2]) or "-"
    cb = ("\n   ⚠️ " + "\n   ⚠️ ".join(kq["canh_bao"])) if kq.get("canh_bao") else ""
    return (f"• {coin} {fg(kq['gia'])} | Ngày {kq.get('bias_d1')} | H4 {kq.get('bias_h4')}\n"
            f"   Hỗ trợ: {ht} | Kháng cự: {kc}"
            + (f" | Đỉnh/đáy hôm qua: {fg(kq['pdh'])}/{fg(kq['pdl'])}" if kq.get("pdh") else "")
            + (f"\n   Dòng tiền: {kq['dong_tien_txt']}" if kq.get("dong_tien_txt") else "") +
            f"\n   → {kq['huong'] or 'ĐỨNG NGOÀI'}: {'; '.join(kq['ly_do'])}{cb}")


# ---------------- Theo dõi kèo đang mở ----------------
def theo_doi(tt, rows, coin, m15, ch):
    phi = ch.get("phi_moi_chieu_phan_tram", 0.05) / 100
    con = []
    for mo in tt.get("keo_mo", []):
        if mo["coin"] != coin:
            con.append(mo)
            continue
        dong = False
        for n in m15[:-1]:   # chỉ nến đã đóng
            if n[0] < mo["t_kiem_tra"]:
                continue
            mo["t_kiem_tra"] = n[0] + TF_MS["15m"]
            dong = cap_nhat_lenh(mo, n, phi)
            if mo["da_tp1"] and not mo.get("da_bao_tp1") and not dong:
                mo["da_bao_tp1"] = True
                gui(f"🎯 Kèo #{mo['id']} {coin} chạm TP1 {fg(mo['tp1'])} → chốt 1/2, dời SL về entry {fg(mo['gia_vao'])}.")
            if dong:
                break
        if not dong and (m15[-1][0] - mo["t_vao"]) > ch.get("het_han_keo_gio", 48) * 3_600_000:
            dong_cuong_buc(mo, m15[-2][4], phi, "hết hạn, đóng theo giá hiện tại")
            dong = True
        if dong:
            ket_thuc(mo, rows, ch, "theo giá")
        else:
            con.append(mo)
    tt["keo_mo"] = con


def ket_thuc(mo, rows, ch, cach, usdt_thuc=None):
    rui_ro = mo["kl"] * abs(mo["gia_vao"] - mo["sl_goc"])
    usdt = mo["lai_lo"] - mo["phi"]
    R_mp = usdt / rui_ro if rui_ro else 0
    R = usdt_thuc / rui_ro if (usdt_thuc is not None and rui_ro) else R_mp
    row = {**{k: mo.get(k, "") for k in tu_hoc.COT_LICH_SU}, "nguon": "bot", "trang_thai": "ĐÓNG",
           "dien_bien": " → ".join(mo["dien_bien"]), "dong_luc": gio(fmt="%Y-%m-%d %H:%M"),
           "R_mo_phong": round(R_mp, 2), "usdt_mo_phong": round(usdt, 2),
           "ket_qua_thuc_usdt": "" if usdt_thuc is None else usdt_thuc, "R": round(R, 2),
           "gia_vao": round(mo["gia_vao"], 2), "sl": round(mo["sl_goc"], 2),
           "tp1": round(mo["tp1"], 2), "tp2": round(mo["tp2"], 2)}
    rows.append(row)
    icon = "✅" if R > 0.2 else "➖" if R > -0.5 else "❌"
    gui(f"{icon} Kèo #{mo['id']} {mo['coin']} {mo['huong']} đã kết thúc ({cach}): {row['dien_bien']}\n"
        f"Kết quả {'thật' if usdt_thuc is not None else 'theo giá (giả định vào đúng giá báo)'}: "
        f"{(usdt_thuc if usdt_thuc is not None else usdt):+.2f}u = {R:+.2f}R\n"
        + ("" if usdt_thuc is not None else f"Lãi/lỗ thật khác? Gõ /kq {mo['id']} +x hoặc -x\n")
        + tu_hoc.ghi_chu_sau_lenh(row, rows))


# ---------------- Lệnh Telegram ----------------
def xu_ly_lenh(tt, ch, rows):
    kiem_tra = False
    try:
        upd = tg("getUpdates", offset=tt.get("offset", 0), timeout=0)["result"]
    except Exception as e:
        print("Lỗi đọc Telegram:", e)
        return False
    for u in upd:
        tt["offset"] = u["update_id"] + 1
        m = u.get("message") or {}
        if str(m.get("chat", {}).get("id")) != CHAT:
            continue
        txt = (m.get("text") or "").strip()
        lenh = txt.lower().split()[0].split("@")[0] if txt else ""
        so_ = re.findall(r"[-+]?\d+(?:[.,]\d+)?", txt)
        if lenh == "/kq":
            if not so_:
                gui("Cách dùng: /kq 12 +3.5 (kèo #12 lãi 3.5u) hoặc /kq -2.5 (kèo gần nhất lỗ 2.5u)")
                continue
            if len(so_) >= 2:
                id_, usdt = int(so_[0]), tu_hoc.so(so_[1])
            else:
                ids = [int(r["id"]) for r in rows if r.get("id")] + [mo["id"] for mo in tt.get("keo_mo", [])]
                id_, usdt = (max(ids) if ids else 0), tu_hoc.so(so_[0])
            mo = next((x for x in tt.get("keo_mo", []) if x["id"] == id_), None)
            if mo:
                tt["keo_mo"].remove(mo)
                mo["dien_bien"].append("bạn tự đóng")
                mo["da_vao"] = "có"
                ket_thuc(mo, rows, ch, "bạn báo", usdt)
                continue
            r = next((x for x in rows if str(x.get("id")) == str(id_)), None)
            if not r:
                gui(f"Không tìm thấy kèo #{id_}.")
                continue
            rr = abs(tu_hoc.so(r["gia_vao"], 0) - tu_hoc.so(r["sl"], 0)) * tu_hoc.so(r["kl"], 0)
            r["ket_qua_thuc_usdt"], r["da_vao"] = usdt, "có"
            r["R"] = round(usdt / rr, 2) if rr else r["R"]
            gui(f"Đã cập nhật kèo #{id_}: {usdt:+.2f}u = {tu_hoc.so(r['R'], 0):+.2f}R.\n" + tu_hoc.ghi_chu_sau_lenh(r, rows))
        elif lenh == "/bo" and so_:
            id_ = int(so_[0])
            for x in tt.get("keo_mo", []) + rows:
                if str(x.get("id")) == str(id_):
                    x["da_vao"] = "không"
            gui(f"Đã ghi: bạn không vào kèo #{id_}. Bot vẫn theo dõi kèo này để tự học, nhưng không tính vào lệnh thua của bạn.")
        elif lenh == "/lichsu":
            cuoi = rows[-10:]
            dong = [f"#{r['id']} {r['coin'].replace('USDT', '')} {r['huong']} {r['vao_luc'][5:]} → {r['dien_bien']} "
                    f"{tu_hoc.so(r['R'], 0):+.2f}R" + (f" (thật {r['ket_qua_thuc_usdt']}u)" if r.get("ket_qua_thuc_usdt") else "")
                    + (" [không vào]" if r.get("da_vao") == "không" else "") for r in cuoi]
            mo = [f"#{x['id']} {x['coin'].replace('USDT', '')} {x['huong']} đang mở ({' → '.join(x['dien_bien']) or 'chưa chạm gì'})"
                  for x in tt.get("keo_mo", [])]
            gui("📜 LỊCH SỬ KÈO\n" + ("\n".join(dong) or "Chưa có kèo đã đóng.") + ("\n\nĐang mở:\n" + "\n".join(mo) if mo else ""))
        elif lenh == "/hoc":
            chan, _ = tu_hoc.goi_y(tu_hoc.lenh_da_xong(rows))
            gui(tu_hoc.bao_cao(rows) + ("\n\nGõ /apdung để bot CHẶN các nhóm trên." if chan else "")
                + (f"\nĐang chặn: {', '.join(tt.get('bo_loc_hoc', []))}" if tt.get("bo_loc_hoc") else ""))
        elif lenh == "/apdung":
            chan, _ = tu_hoc.goi_y(tu_hoc.lenh_da_xong(rows))
            tt["bo_loc_hoc"] = sorted(set(tt.get("bo_loc_hoc", [])) | {f for f, _ in chan})
            gui("✅ Đã áp dụng. Bot sẽ bỏ kèo thuộc: " + (", ".join(tt["bo_loc_hoc"]) or "(chưa có nhóm nào đủ dữ liệu)")
                + "\nGõ /bohoc để huỷ.")
        elif lenh == "/bohoc":
            tt["bo_loc_hoc"] = []
            gui("Đã bỏ hết bộ lọc tự học.")
        elif lenh == "/tinlon":
            ds = [f"• {t:%a %d/%m %H:%M} — {ten}" for t, ten in ds_tin(ch, tt) if t >= bay_gio() - dt.timedelta(hours=2)]
            gui("📅 Tin USD tác động mạnh (giờ VN):\n" + ("\n".join(ds) or "Không còn tin lớn tuần này / chưa tải được."))
        elif lenh == "/thua":
            tt["thua"] += 1
            gui(f"Đã ghi thêm 1 lệnh thua hôm nay (ngoài kèo bot).")
        elif lenh == "/thang":
            gui("Ghi nhận! Lần sau dùng /kq <số kèo> +lãi để bot học được kèo nào hiệu quả.")
        elif lenh == "/tat":
            tt["tat"] = True
            gui("🔕 Đã tạm tắt báo kèo (vẫn nhắc tin lớn và theo dõi kèo đang mở). /bat để bật lại.")
        elif lenh == "/bat":
            tt["tat"] = False
            gui("🔔 Đã bật lại báo kèo.")
        elif lenh == "/trangthai":
            gui(f"📊 Hôm nay {gio(fmt='%d/%m')}: thua {so_thua_hom_nay(tt, rows)} lệnh, đã báo {tt['keo_da_bao']} kèo, "
                f"{len(tt.get('keo_mo', []))} kèo đang mở.\nBáo kèo: {'TẮT' if tt.get('tat') else 'BẬT'}."
                + (f"\nBộ lọc tự học: {', '.join(tt['bo_loc_hoc'])}" if tt.get("bo_loc_hoc") else ""))
        elif lenh == "/kiemtra":
            kiem_tra = True
        elif lenh in ("/start", "/help"):
            gui(__doc__.split("Lệnh nhắn cho bot")[1].strip())
    return kiem_tra


def canh_bao_dom(tt, ch, btc_h1, dong_tien):
    """Kinh nghiệm: BTC hút dom để test rồi sập -> ETH sập mạnh hơn."""
    if not ch.get("canh_bao_dom", True) or "ethbtc" not in dong_tien or not btc_h1:
        return
    bn = bay_gio()
    xh = dong_tien["ethbtc"].tai(int(bn.timestamp() * 1000))
    dom24 = dong_tien.get("dom_24h")
    loai = None
    if btc_h1 == "TĂNG" and xh == "GIẢM" and (dom24 is None or dom24 >= 0.3):
        loai = ("hut", "👀 BTC ĐANG HÚT DOM: BTC H1 tăng nhưng ETH/BTC H4 giảm"
                + (f", BTC.D {dom24:+.2f} điểm/24h" if dom24 is not None else "") +
                ".\nETH đang tụt lại phía sau. Nếu BTC test kháng cự xong rồi gãy, ETH thường sập mạnh hơn.\n"
                "👉 Không LONG ETH đuổi theo BTC. Chờ BTC gãy cấu trúc H1 để tìm SHORT ETH.")
    elif btc_h1 == "GIẢM" and xh == "GIẢM":
        loai = ("sap", "⚠️ BTC GÃY TRONG LÚC ETH/BTC ĐANG GIẢM: ETH thường sập mạnh hơn BTC giai đoạn này.\n"
                "👉 Không bắt đáy ETH. Nếu SHORT, ETH thường chạy xa hơn BTC — vẫn giữ đúng SL.")
    if loai and bn.timestamp() - tt.get("dom_bao_" + loai[0], 0) >= ch.get("khong_bao_dom_lai_gio", 6) * 3600:
        tt["dom_bao_" + loai[0]] = bn.timestamp()
        gui(loai[1])


def so_thua_hom_nay(tt, rows):
    hn = gio(fmt="%Y-%m-%d")
    return tt.get("thua", 0) + sum(1 for r in rows if r.get("dong_luc", "").startswith(hn)
                                   and tu_hoc.so(r.get("R"), 0) <= -0.5 and r.get("da_vao") != "không")


# ---------------- Chạy chính ----------------
def main():
    ch = doc_json(os.path.join(THU_MUC, "cau_hinh.json"), None)
    if not ch:
        sys.exit("Thiếu hoặc lỗi file cau_hinh.json")
    if not DEMO and (not TOKEN or not CHAT):
        sys.exit("Chưa có TELEGRAM_TOKEN / TELEGRAM_CHAT_ID trong GitHub Secrets")
    tt = doc_json(FILE_TT, {})
    if tt.get("ngay") != gio(fmt="%Y-%m-%d"):
        tt.update(ngay=gio(fmt="%Y-%m-%d"), thua=0, keo_da_bao=0, da_bao_dung=False, fake_hom_nay=0)
    tt.setdefault("da_bao", {})
    rows = doc_lich_su()

    if not tt.get("da_chao"):
        gui("✅ Bot báo kèo V3 đã chạy! Theo dõi " + ", ".join(ch["coins"])
            + " mỗi 15 phút, nhắc tin lớn trước 24 giờ, tự theo dõi kết quả kèo và tự học.\nGõ /help để xem lệnh.")
        tt["da_chao"] = True

    try:
        chay_mot_luot(ch, tt, rows)
    finally:   # có lỗi giữa chừng vẫn lưu, tránh xử lý lặp lệnh Telegram
        ghi_lich_su(rows)
        with open(FILE_TT, "w", encoding="utf-8") as f:
            json.dump(tt, f, ensure_ascii=False, indent=1)


def chay_mot_luot(ch, tt, rows):
    kiem_tra = xu_ly_lenh(tt, ch, rows)
    cap_nhat_lich_tin(tt)
    nhac_tin(ch, tt)
    try:
        btc_h1 = xu_huong_nhanh(chi_nen_da_dong(du_lieu_demo(30, 77400)["1h"] if DEMO else lay_nen("BTCUSDT", "1h", 200)[0],
                                                "1h", int(bay_gio().timestamp() * 1000)))
    except Exception:
        btc_h1 = None

    dong_tien = {}
    if "ETHUSDT" in ch["coins"]:
        try:
            nen_eb = du_lieu_demo(150, 0.03, seed=9)["4h"] if DEMO else lay_nen("ETHBTC", "4h", 200)[0]
            dong_tien["ethbtc"] = TheoDoiCap(chi_nen_da_dong(nen_eb, "4h", int(bay_gio().timestamp() * 1000)))
        except Exception as e:
            print("Lỗi ETH/BTC:", e)
    dong_tien["dom"], dong_tien["dom_24h"] = cap_nhat_dom(tt)
    canh_bao_dom(tt, ch, btc_h1, dong_tien)

    tom = []
    for coin in ch["coins"]:
        try:
            data, nguon = lay_du_lieu(coin)
            theo_doi(tt, rows, coin, data["15m"], ch)
            kq = phan_tich(coin, data, nguon, ch, dong_tien, tt["da_bao"].get(coin + "_nen"))
        except Exception as e:
            print(coin, "lỗi:", e)
            if kiem_tra:
                tom.append(f"• {coin}: lỗi lấy dữ liệu ({e})")
            continue
        if kiem_tra:
            tom.append(tom_tat(coin, kq))
        if tt["da_bao"].get(coin + "_nen") == kq["t_nen"]:
            continue   # mỗi nến M15 chỉ xét 1 lần
        tt["da_bao"][coin + "_nen"] = kq["t_nen"]
        if tt.get("tat"):
            continue
        if so_thua_hom_nay(tt, rows) >= ch["thua_toi_da_ngay"]:
            if not tt["da_bao_dung"]:
                gui("⛔ Đã thua đủ số lệnh cho phép hôm nay. Bot ngừng báo kèo tới ngày mai. Đừng trả thù thị trường.")
                tt["da_bao_dung"] = True
            continue

        if kq["huong"] and coin != "BTCUSDT" and ch.get("loc_theo_btc", True) and btc_h1:
            if (kq["huong"] == "LONG" and btc_h1 == "GIẢM") or (kq["huong"] == "SHORT" and btc_h1 == "TĂNG"):
                kq["huong"] = None
        if kq["huong"]:
            dt_ = {"coin": coin, "huong": kq["huong"], "vao_luc": gio(kq["t_nen"] + TF_MS["15m"], "%Y-%m-%d %H:%M"),
                   "khung_gio": kq["khung_gio"], "bias_d1": kq["bias_d1"], "so_xac_nhan": kq["so_xac_nhan"],
                   "ethbtc": kq.get("ethbtc", ""),
                   "canh_bao": " | ".join(kq["canh_bao"])}
            khoa = f"{coin}_{kq['huong']}"
            if kq["t_nen"] - tt["da_bao"].get(khoa, 0) < ch["khong_bao_lai_trong_gio"] * 3_600_000:
                continue
            if tt["keo_da_bao"] >= ch["toi_da_keo_moi_ngay"] or any(x["coin"] == coin for x in tt.get("keo_mo", [])):
                continue
            tt["da_bao"][khoa] = kq["t_nen"]
            tin = dang_gan_tin(ch, tt)
            if tin:
                gui(f"ℹ️ {coin} có setup {kq['huong']} nhưng gần giờ tin lớn ({tin}) — BỎ QUA theo quy tắc.")
                continue
            loc = tu_hoc.bi_chan_boi(tu_hoc.dac_trung(dt_), tt.get("bo_loc_hoc", []))
            if loc:
                gui(f"ℹ️ {coin} có setup {kq['huong']} nhưng thuộc nhóm bạn đã chặn (tự học): {loc} — BỎ QUA.")
                continue
            sl = kq["sl"]
            kl = lam_tron_kl(coin, ch["rui_ro_usdt"] / sl, ch.get("buoc_khoi_luong", {}).get(coin))
            if kl <= 0:
                continue
            tt["id_tiep"] = tt.get("id_tiep", 0) + 1
            mo = tao_lenh(kq["huong"], kq["gia"], sl, ch["rr"], kl, ch.get("phi_moi_chieu_phan_tram", 0.05) / 100)
            mo.update(dt_, id=tt["id_tiep"], kl=kl, t_vao=kq["t_nen"] + TF_MS["15m"], t_kiem_tra=kq["t_nen"] + TF_MS["15m"], da_vao="")
            tt.setdefault("keo_mo", []).append(mo)
            tt["keo_da_bao"] += 1
            gui(tin_keo(mo["id"], coin, kq, ch, kl, round(kl * sl, 2)))
        elif (ch.get("bao_canh_bao_fake") and any("BẪY" in x for x in kq["canh_bao"])
              and kq["t_nen"] - tt["da_bao"].get(coin + "_fake", 0) >= ch.get("khong_bao_fake_lai_gio", 4) * 3_600_000
              and tt.get("fake_hom_nay", 0) < ch.get("toi_da_canh_bao_fake_ngay", 3)):
            # Chỉ báo BẪY (quét thanh khoản) — không báo phá vỡ yếu lẻ tẻ; tối đa vài tin/ngày
            tt["da_bao"][coin + "_fake"] = kq["t_nen"]
            tt["fake_hom_nay"] = tt.get("fake_hom_nay", 0) + 1
            gui(f"👀 {coin} {fg(kq['gia'])} — cảnh báo nhịp fake ({gio(kq['t_nen'] + TF_MS['15m'])}):\n"
                + "\n".join("⚠️ " + x for x in kq["canh_bao"]) + "\nĐừng đuổi giá lúc này.")

    if kiem_tra:
        gui("🔎 PHÂN TÍCH NHANH " + gio() + "\n\n" + "\n\n".join(tom) + "\n\n(Theo quy tắc, không phải lời khuyên tài chính.)")

    # Báo cáo tự học mỗi Chủ nhật từ 20h
    bn = bay_gio()
    if ch.get("bao_cao_tuan", True) and bn.weekday() == 6 and bn.hour >= 20 and tt.get("hoc_tuan") != bn.strftime("%Y-%m-%d"):
        tt["hoc_tuan"] = bn.strftime("%Y-%m-%d")
        gui("🗓 BÁO CÁO TUẦN\n" + tu_hoc.bao_cao(rows))


if __name__ == "__main__":
    main()
