from __future__ import annotations

from io import BytesIO
from urllib.parse import quote

import qrcode

# Napas BIN cho VN banks (xem https://api.vietqr.io/v2/banks)
BANK_BIN: dict[str, str] = {
    "MB": "970422",
    "MBB": "970422",
    "BIDV": "970418",
    "ACB": "970416",
    "VCB": "970436",
    "TCB": "970407",
    "VPB": "970432",
    "TPB": "970423",
    "ICB": "970415",  # Vietinbank
    "VTB": "970415",
    "VBA": "970405",  # Agribank
    "AGRIBANK": "970405",
    "STB": "970403",  # Sacombank
    "HDB": "970437",  # HDBank
    "MSB": "970426",  # Maritime Bank
    "OCB": "970448",
    "VIB": "970441",
    "SHB": "970443",
    "EIB": "970431",  # Eximbank
    "SCB": "970429",
    "NAB": "970428",  # Nam A Bank
    "ABB": "970425",  # An Binh
    "BVB": "970438",  # Bao Viet
    "SEAB": "970440",
    "PVCB": "970412",  # PVcomBank
    "VCCB": "970454",
    "GPB": "970408",
    "WVN": "970457",  # Woori
    "UOB": "970458",
    "PBVN": "970439",  # Public Bank
    "CIMB": "422589",
    "KLB": "970452",  # Kien Long
    "VAB": "970427",  # VietA
    "BAB": "970409",  # BacA
    "NCB": "970419",
    "LPB": "970449",  # LienVietPostBank
    "BVBANK": "970454",
}


def tlv(tag: str, value: str) -> str:
    return f"{tag}{len(value):02d}{value}"


def crc16_ccitt_false(value: str) -> str:
    crc = 0xFFFF
    for byte in value.encode("ascii"):
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
            crc &= 0xFFFF
    return f"{crc:04X}"


def generate_vietqr_payload(
    *, bank_bin: str, account_no: str, amount_vnd: int, content: str
) -> str:
    beneficiary = tlv("00", "A000000727") + tlv("01", tlv("00", bank_bin) + tlv("01", account_no))
    merchant_account = tlv("38", beneficiary)
    additional_data = tlv("62", tlv("08", content))
    payload_without_crc = "".join(
        [
            tlv("00", "01"),
            tlv("01", "11"),
            merchant_account,
            tlv("53", "704"),
            tlv("54", str(amount_vnd)),
            tlv("58", "VN"),
            additional_data,
            "6304",
        ]
    )
    return payload_without_crc + crc16_ccitt_false(payload_without_crc)


def generate_qr_png(payload: str) -> bytes:
    image = qrcode.make(payload)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def vietqr_image_url(
    *,
    bank_code: str,
    account_no: str,
    amount_vnd: int,
    content: str,
    account_holder: str | None = None,
    template: str = "qr_only",
) -> str:
    """Trả URL ảnh QR sinh bởi service VietQR (img.vietqr.io).

    URL này được app banking VN scan tốt hơn so với payload TLV tự sinh
    (vì có sẵn service code QRIBFTTA + checksum đã chuẩn). CSP đã whitelist
    domain `img.vietqr.io` nên ảnh hiển thị được trực tiếp trên web app.

    Mặc định dùng template `qr_only` để có ô QR vuông, không branding —
    sắc nét, app banking nào cũng quét được. Các template khác (`compact`,
    `compact2`, `print`) có thêm logo/branding nhưng làm ô QR thực bị thu
    nhỏ, dễ quét sai trên màn hình laptop.

    Format: https://img.vietqr.io/image/<BANK>-<ACC>-<TEMPLATE>.png?amount=...&addInfo=...&accountName=...
    """
    base = f"https://img.vietqr.io/image/{bank_code.upper()}-{account_no}-{template}.png"
    params = [f"amount={int(amount_vnd)}", f"addInfo={quote(content, safe='')}"]
    if account_holder:
        params.append(f"accountName={quote(account_holder, safe='')}")
    return base + "?" + "&".join(params)
