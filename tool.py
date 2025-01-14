import time
import os
import sys
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service

# Cấu hình UTF-8 cho đầu ra terminal
sys.stdout.reconfigure(encoding='utf-8')
# Định nghĩa các trạng thái hội thoại
WAITING_INFO, WAITING_OTP = range(2)

# Lưu trữ thông tin người dùng tạm thời
user_data = {}

# Biến cờ bật/tắt chế độ chạy nền
headless_mode = True  # Đặt True để chạy nền, False để xem trình duyệt

def kill_firefox_processes():
    """Kill tất cả các process Firefox và geckodriver trên Windows"""
    try:
        os.system("taskkill /f /im firefox.exe >nul 2>&1")
        os.system("taskkill /f /im geckodriver.exe >nul 2>&1")
        time.sleep(3)  # Đợi process được kill hoàn toàn
    except Exception as e:
        print(f"Lỗi khi kill Firefox: {str(e)}")

# Thêm biến toàn cục để theo dõi phiên người dùng
active_sessions = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bắt đầu một phiên mới."""
    user_id = update.effective_user.id

    # Kiểm tra nếu người dùng đã có phiên hoạt động
    if active_sessions.get(user_id):
        await update.message.reply_text(
            "⚠️ Bạn đang có một phiên hoạt động. Nhập /cancel để hủy trước khi bắt đầu mới."
        )
        return ConversationHandler.END

    # Đánh dấu phiên người dùng đang hoạt động
    active_sessions[user_id] = True

    await update.message.reply_text(
        "Chào mừng bạn đến với bot đổi mật khẩu VTC!\n"
        "Hãy nhập thông tin theo định dạng sau:\n"
        "`tài khoản|mật khẩu cũ|mật khẩu mới|số điện thoại|Y/N`\n"
        "(Y: hủy xác thực số điện thoại, N: không hủy xác thực)",
        parse_mode='Markdown'
    )
    return WAITING_INFO

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Hủy thao tác hiện tại và dọn dẹp tài nguyên."""
    user_id = update.effective_user.id

    # Kiểm tra nếu người dùng có phiên hoạt động
    if not active_sessions.get(user_id):
        await update.message.reply_text("❌ Không có phiên hoạt động để hủy.")
        return ConversationHandler.END

    # Dọn dẹp tài nguyên và đánh dấu phiên không hoạt động
    cleanup_driver(user_id)
    await update.message.reply_text("❌ Đã hủy thao tác và dọn dẹp tài nguyên.")
    return ConversationHandler.END

async def update_status(update: Update, message: str):
    """Gửi thông báo trạng thái tới người dùng."""
    await update.message.reply_text(message)


def cleanup_driver(user_id):
    """Dọn dẹp trình duyệt và xóa dữ liệu người dùng"""
    session = user_data.pop(user_id, None)
    if session and session.get('driver'):
        try:
            session['driver'].quit()
        except Exception as e:
            print(f"Lỗi khi đóng driver: {str(e)}")
        finally:
            kill_firefox_processes()

    active_sessions.pop(user_id, None)

async def process_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    info = update.message.text

    try:
        # Kill Firefox hiện tại
        kill_firefox_processes()

        # Split input including the Y/N option
        parts = info.split('|')
        if len(parts) != 5:
            await update.message.reply_text("❌ Vui lòng nhập đúng định dạng: tài khoản|mật khẩu cũ|mật khẩu mới|số điện thoại|Y/N")
            return ConversationHandler.END

        username, password, newpass, phone, unverify_option = parts

        # Validate Y/N option
        if unverify_option.upper() not in ['Y', 'N']:
            await update.message.reply_text("❌ Tùy chọn hủy xác thực phải là Y hoặc N")
            return ConversationHandler.END

        user_data[user_id] = {
            'username': username,
            'password': password,
            'newpass': newpass,
            'phone': phone,
            'unverify': unverify_option.upper() == 'Y',
            'driver': None
        }

        # Cài đặt Firefox chạy ẩn hoặc không
        firefox_options = Options()
        if headless_mode:
            firefox_options.add_argument('--headless')

        firefox_options.add_argument('--disable-gpu')
        firefox_options.add_argument('--no-sandbox')
        firefox_options.add_argument('--disable-dev-shm-usage')
        firefox_options.page_load_strategy = 'normal'

        service = Service(log_output=None)
        driver = webdriver.Firefox(options=firefox_options, service=service)
        driver.maximize_window()
        driver.set_page_load_timeout(45)
        user_data[user_id]['driver'] = driver

        # Quá trình đăng nhập
        await update_status(update, "⏳ Đang mở trang đăng nhập...")
        driver.get("https://vtcgame.vn/bao-mat/smsplus")
        time.sleep(1)

        wait = WebDriverWait(driver, 60)

        await update_status(update, "⌨️ Đang nhập thông tin đăng nhập...")
        username_field = wait.until(EC.presence_of_element_located((By.ID, "phone_number")))
        time.sleep(1)
        username_field.clear()
        time.sleep(1)
        username_field.send_keys(username)
        time.sleep(1)

        password_field = driver.find_element(By.ID, "txtPass")
        password_field.clear()
        time.sleep(1)
        password_field.send_keys(password)
        time.sleep(2)

        await update_status(update, "🔄 Đang xử lý đăng nhập...")
        login_button = driver.find_element(By.XPATH, "//a[@onclick='checkValidRegByMobile();']")
        login_button.click()
        time.sleep(3)

        await update_status(update, "📱 Đang thiết lập SMS Plus...")
        show_popup_button = wait.until(EC.presence_of_element_located((By.XPATH, "//a[@onclick='Account.ShowPopupSMSPlus(false);']")))
        time.sleep(2)
        show_popup_button.click()
        time.sleep(2)

        phone_input = wait.until(EC.presence_of_element_located((By.ID, "txtPhone")))
        phone_input.clear()
        time.sleep(1)
        phone_input.send_keys(phone)
        time.sleep(2)

        step1_button = wait.until(EC.element_to_be_clickable((By.ID, "step1")))
        step1_button.click()
        time.sleep(2)

        await update_status(update, "📤 Vui lòng đợi tin nhắn OTP và nhập mã OTP:")
        return WAITING_OTP

    except Exception as e:
        await update_status(update, f"❌ Có lỗi xảy ra: {e}")
        cleanup_driver(user_id)
        return ConversationHandler.END

async def process_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    otp = update.message.text
    driver = user_data[user_id]['driver']

    try:
        wait = WebDriverWait(driver, 30)

        # Xác thực SMS Plus
        await update_status(update, "🔐 Đang xác thực SMS Plus...")
        otp_input = wait.until(EC.presence_of_element_located((By.ID, "txtOTPPhone")))
        time.sleep(3)
        otp_input.clear()
        time.sleep(1)
        otp_input.send_keys(otp)
        time.sleep(1)

        confirm_button = driver.find_element(By.CLASS_NAME, "popup-body__btn")
        confirm_button.click()
        time.sleep(1)

        # Đổi mật khẩu
        await update_status(update, "🔄 Đang chuyển sang trang đổi mật khẩu...")
        driver.get("https://vtcgame.vn/bao-mat/doi-mat-khau")
        time.sleep(1)

        await update_status(update, "🔄 Đang đổi mật khẩu...")
        old_password_input = wait.until(EC.presence_of_element_located((By.ID, "txtPassOld")))
        time.sleep(1)
        old_password_input.clear()
        time.sleep(1)
        old_password_input.send_keys(user_data[user_id]['password'])
        time.sleep(2)

        btn_primary = wait.until(EC.element_to_be_clickable((By.CLASS_NAME, "btn.btn-primary")))
        time.sleep(1)
        btn_primary.click()
        time.sleep(1)

        otp_input = wait.until(EC.presence_of_element_located((By.ID, "txtOtp")))
        time.sleep(1)
        otp_input.clear()
        time.sleep(1)
        otp_input.send_keys(otp)
        time.sleep(2)

        confirm_button = wait.until(EC.element_to_be_clickable((By.CLASS_NAME, 'popup-body__btn')))
        time.sleep(1)
        confirm_button.click()
        time.sleep(1)

        new_password_input = wait.until(EC.presence_of_element_located((By.ID, "txtNewPass")))
        time.sleep(1)
        new_password_input.clear()
        time.sleep(1)
        new_password_input.send_keys(user_data[user_id]['newpass'])
        time.sleep(1)

        re_new_password_input = driver.find_element(By.ID, "txtReNewPass")
        re_new_password_input.clear()
        time.sleep(1)
        re_new_password_input.send_keys(user_data[user_id]['newpass'])
        time.sleep(1)

        btn_capnhat = wait.until(EC.element_to_be_clickable((By.CLASS_NAME, "popup-body__btn")))
        btn_capnhat.click()
        time.sleep(1)

        # Hủy xác thực số điện thoại (nếu được chọn)
        if user_data[user_id]['unverify']:
            await update_status(update, "📱 Đang hủy xác thực số điện thoại...")
            driver.get("https://vtcgame.vn/thong-tin-tai-khoan")
            time.sleep(1)

            driver.execute_script("Account.UnVerifyPhoneNew();")
            time.sleep(1)

            otp_input = wait.until(EC.presence_of_element_located((By.ID, "txtOTPPhone")))
            
            otp_input.clear()
            time.sleep(1)
            otp_input.send_keys(otp)
            time.sleep(1)

            unverify_confirm_button = wait.until(EC.element_to_be_clickable((By.CLASS_NAME, "popup-body__btn")))
            unverify_confirm_button.click()
            time.sleep(1)

        if user_data[user_id]['unverify']:
            await update_status(update, "✅ Đã đổi mật khẩu và hủy xác thực số điện thoại thành công!")
        else:
            await update_status(update, "✅ Đã đổi mật khẩu thành công! Số điện thoại vẫn được giữ nguyên.")
    except Exception as e:
        await update_status(update, f"❌ Có lỗi xảy ra: {e}")
    finally:
        cleanup_driver(user_id)
        return ConversationHandler.END

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gửi hướng dẫn sử dụng bot."""
    help_text = (
        "🛠 **Hướng dẫn sử dụng bot đổi mật khẩu VTC** 🛠\n\n"
        "⚡ **Lệnh chính:**\n"
        " - /start: Bắt đầu một phiên mới.\n"
        " - /cancel: Hủy phiên đang chạy và dọn dẹp tài nguyên.\n"
        " - /help: Hiển thị hướng dẫn sử dụng.\n\n"
        "⚡ **Quy trình đổi mật khẩu:**\n"
        "1️⃣ Nhập thông tin theo định dạng:\n"
        "`tài khoản|mật khẩu cũ|mật khẩu mới|số điện thoại|Y/N`\n"
        "(Y: hủy xác thực số điện thoại, N: không hủy xác thực)\n\n"
        "2️⃣ Nhập mã OTP khi được yêu cầu.\n"
        "3️⃣ Hoàn tất việc đổi mật khẩu.\n\n"
        "Nếu gặp lỗi, vui lòng kiểm tra thông tin đầu vào hoặc thử lại sau."
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')
   



def main():
    # Kill tất cả Firefox process khi khởi động bot
    kill_firefox_processes()

    application = Application.builder().token('7421795489:AAHxzwHc2-7cQFprdPA5_MgRFU3nJNpskY8').build()
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            WAITING_INFO: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_info)],
            WAITING_OTP: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_otp)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    application.add_handler(conv_handler)
    print("Bot đã sẵn sàng và đang chạy...", flush=True)
    
    
    application.add_handler(CommandHandler('help', help_command))
    application.run_polling(allowed_updates=Update.ALL_TYPES)
    



if __name__ == '__main__':
    main()
