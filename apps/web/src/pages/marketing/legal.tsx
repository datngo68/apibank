import { Helmet } from "react-helmet-async";

export function TermsPage() {
  return (
    <>
      <Helmet><title>Điều khoản sử dụng · APIBank</title></Helmet>
      <article className="container prose prose-sm max-w-3xl py-12 dark:prose-invert">
        <h1>Điều khoản sử dụng</h1>
        <p>APIBank cung cấp dịch vụ nhận biến động số dư và xác thực giao dịch tự động. Khi đăng ký bạn đồng ý:</p>
        <ul>
          <li>Cung cấp thông tin chính xác và bảo mật tài khoản đăng nhập.</li>
          <li>Không sử dụng nền tảng cho mục đích trái pháp luật.</li>
          <li>Chấp nhận rằng adapter ngân hàng bên thứ ba có thể bị nhà phát hành tạm khóa; APIBank không chịu trách nhiệm thiệt hại gián tiếp.</li>
        </ul>
        <h2>Hoàn tiền</h2>
        <p>Hoàn tiền 100% nếu không vừa ý dịch vụ trong vòng 7 ngày sau khi mua gói.</p>
        <h2>Liên hệ</h2>
        <p>Mọi vấn đề pháp lý vui lòng gửi về email được niêm yết trong dashboard quản trị.</p>
      </article>
    </>
  );
}

export function PrivacyPage() {
  return (
    <>
      <Helmet><title>Chính sách bảo mật · APIBank</title></Helmet>
      <article className="container prose prose-sm max-w-3xl py-12 dark:prose-invert">
        <h1>Chính sách bảo mật</h1>
        <p>Chúng tôi cam kết bảo vệ thông tin của bạn:</p>
        <ul>
          <li>Mật khẩu được hash bằng bcrypt với pre-hash SHA-256.</li>
          <li>Credential ngân hàng được mã hóa Fernet trước khi lưu DB; chỉ giải mã khi cần đăng nhập.</li>
          <li>Mọi hành động nhạy cảm được ghi audit log có IP và user agent.</li>
          <li>Bạn có thể yêu cầu xuất dữ liệu cá nhân (GDPR-style) hoặc xoá tài khoản bất cứ lúc nào.</li>
        </ul>
      </article>
    </>
  );
}
