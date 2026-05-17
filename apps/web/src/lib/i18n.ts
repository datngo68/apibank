/*
 * Khởi tạo i18n cho FE — bắt đầu với vi (default) + en stub.
 *
 * Mở rộng: thêm bundle JSON cho từng namespace, lazy import per route.
 * Hiện tại nội dung Việt nằm trực tiếp trong page (đã viết tiếng Việt).
 * i18next sẽ dùng cho các chuỗi label/thông báo dùng chung.
 */

import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import LanguageDetector from "i18next-browser-languagedetector";

const resources = {
  vi: {
    common: {
      app_name: "APIBank",
      sign_in: "Đăng nhập",
      sign_up: "Đăng ký",
      logout: "Đăng xuất",
      dashboard: "Dashboard",
      something_went_wrong: "Có lỗi xảy ra, vui lòng thử lại.",
    },
  },
  en: {
    common: {
      app_name: "APIBank",
      sign_in: "Sign in",
      sign_up: "Register",
      logout: "Sign out",
      dashboard: "Dashboard",
      something_went_wrong: "Something went wrong. Please try again.",
    },
  },
};

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources,
    fallbackLng: "vi",
    supportedLngs: ["vi", "en"],
    defaultNS: "common",
    interpolation: { escapeValue: false },
    detection: {
      order: ["localStorage", "navigator"],
      caches: ["localStorage"],
      lookupLocalStorage: "apibank.locale",
    },
  })
  .catch(() => undefined);

export default i18n;
