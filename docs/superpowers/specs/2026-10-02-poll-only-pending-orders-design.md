# Thiết kế: chỉ poll ngân hàng khi có đơn chờ thanh toán

## Mục tiêu

Giảm số lần truy cập Internet Banking, đặc biệt với MB, để hạn chế ảnh hưởng đến phiên đăng nhập trên ứng dụng mobile. Mỗi tài khoản ngân hàng có thể được cấu hình chỉ lấy lịch sử giao dịch khi có đơn hàng đang chờ thanh toán.

## Phạm vi

- Tùy chọn được cấu hình riêng cho từng `BankAccount`.
- Mọi `Order` pending gắn với tài khoản đều có thể kích hoạt polling, bao gồm đơn thanh toán API và top-up.
- Tài khoản MB mới mặc định bật tùy chọn.
- Migration bật tùy chọn cho các tài khoản MB hiện có; ngân hàng khác mặc định tắt.
- Không thay đổi cơ chế matching, ingest giao dịch hoặc vòng đời đơn hàng.

## Mô hình dữ liệu

Thêm cột boolean `poll_only_when_pending` vào `bank_accounts`.

- `true`: chỉ gọi adapter ngân hàng nếu tồn tại đơn pending chưa hết hạn.
- `false`: poll liên tục theo `poll_interval` như hiện tại.
- Giá trị mặc định ở database là `false` để tương thích chung.
- API tạo tài khoản đặt `true` khi `bank_code == "MB"`, ngược lại đặt `false`.
- Migration cập nhật các bản ghi MB hiện có thành `true`.

## API và giao diện

### API

Bổ sung `poll_only_when_pending` vào schema đọc tài khoản ngân hàng và endpoint cập nhật tài khoản hiện có. Endpoint phải kiểm tra ownership theo cơ chế đang dùng cho các thao tác tài khoản ngân hàng.

Khi tùy chọn thay đổi, API commit dữ liệu rồi phát tín hiệu đánh thức/rescan worker để trạng thái mới có hiệu lực mà không cần restart.

### UI

Đặt switch trên trang **Tài khoản ngân hàng** cho từng tài khoản:

- Nhãn: `Chỉ kiểm tra giao dịch khi có đơn chờ thanh toán`.
- Mô tả: `Giảm truy cập Internet Banking và hạn chế ảnh hưởng đến phiên app mobile.`
- Switch hiển thị giá trị hiện tại và cập nhật qua API.
- Hiển thị trạng thái lưu và thông báo lỗi theo pattern UI hiện có.

## Luồng worker

Trước mỗi lần gọi `adapter.list_transactions`, worker xác định tài khoản có cần poll hay không:

1. Nếu `poll_only_when_pending == false`, tiếp tục poll như hiện tại.
2. Nếu `true`, truy vấn tồn tại `Order` thỏa cả ba điều kiện:
   - `Order.bank_account_id == account.id`.
   - `Order.status == "pending"`.
   - `Order.expired_at > now`.
3. Nếu có đơn phù hợp, worker poll và ingest như hiện tại.
4. Nếu không có, worker không gọi MB, không login và chuyển sang chờ `poll_kick` hoặc hết `poll_interval`.

Kiểm tra phải dùng truy vấn `EXISTS` hoặc truy vấn giới hạn một dòng, không tải danh sách đơn hàng.

Trạng thái tài khoản khi đang chờ đơn vẫn là trạng thái hợp lệ, không ghi nhận lỗi. Có thể dùng `polling_status = "waiting_order"` để dashboard phản ánh chính xác rằng worker đang hoạt động nhưng chưa cần gọi ngân hàng.

## Đánh thức worker

Các luồng tạo đơn phải gọi `poll_kick.kick(bank_account_id)` sau khi transaction tạo đơn đã commit. Điều này áp dụng cho mọi loại đơn pending trong phạm vi tính năng.

Luồng nút `Tôi đã chuyển khoản` tiếp tục kick worker như hiện tại. Worker vẫn kiểm tra database định kỳ theo `poll_interval`, nên mất Redis event không làm mất khả năng xử lý lâu dài.

Khi đơn chuyển sang paid, canceled hoặc expired, chu kỳ worker kế tiếp sẽ thấy không còn đơn hợp lệ và ngừng gọi MB.

## Quản lý session

- Khi không có đơn pending, worker không gọi API MB và không tạo login mới.
- Session đã mã hóa trong `session_enc` vẫn được giữ nguyên.
- Khi có đơn mới, worker khôi phục và dùng session cũ trước.
- Chỉ khi MB không chấp nhận session thì thư viện mới thực hiện xác thực lại theo cơ chế hiện tại.

## Tính đúng đắn và cạnh tranh

- Đơn được tạo giữa lúc worker kiểm tra và bắt đầu chờ sẽ gửi `poll_kick`, giúp worker thức ngay.
- Nếu event đến trước khi worker bắt đầu chờ, safety poll theo `poll_interval` đảm bảo độ trễ tối đa hữu hạn.
- Đơn hết hạn nhưng chưa được reconcile sang trạng thái `expired` vẫn không kích hoạt poll vì điều kiện kiểm tra `expired_at > now`.
- Đơn của tài khoản khác không được kích hoạt worker này.

## Kiểm thử

### Backend

- Tùy chọn tắt: worker poll dù không có đơn pending.
- Tùy chọn bật, không có đơn: adapter không được gọi.
- Có đơn pending chưa hết hạn: adapter được gọi.
- Đơn pending đã hết hạn: adapter không được gọi.
- Đơn pending thuộc tài khoản khác: adapter không được gọi.
- API đọc và cập nhật trường mới đúng ownership.
- Tạo đơn phát `poll_kick` sau commit.
- Migration có một head hợp lệ và cập nhật tài khoản MB hiện có.

### Frontend

- Switch hiển thị đúng giá trị từ API.
- Thay đổi switch gửi đúng payload.
- Thành công cập nhật cache/UI; lỗi khôi phục trạng thái và hiển thị thông báo.

## Triển khai

1. Chạy test và lint tại local.
2. Push commit lên `main`.
3. Đồng bộ code lên VPS.
4. Chạy migration trước khi recreate API/worker.
5. Rebuild và restart `api`, `worker`, `scheduler` nếu cần.
6. Xác minh migration head, API health và worker log.
7. Xác minh tài khoản MB hiện có có `poll_only_when_pending = true`.
8. Khi không có đơn pending, xác minh `last_poll_at` không tiếp tục thay đổi và không xuất hiện request/login MB mới.
9. Tạo một đơn thử nghiệm và xác minh worker được đánh thức, poll, rồi ngừng sau khi đơn kết thúc.

## Không thuộc phạm vi

- Tích hợp Casso/SePay.
- Thay đổi thuật toán matching giao dịch.
- Thay đổi thời hạn đơn hàng.
- Xây dựng webhook ngân hàng mới.
- Sửa healthcheck Docker của worker/scheduler.
