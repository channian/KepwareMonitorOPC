import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging


class EmailService:
    def __init__(self, smtp_server, smtp_port, sender_email, sender_name="Kepware Monitor"):
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.sender_email = sender_email
        self.sender_name = sender_name

    def send_alert_email(self, to_addresses, subject, html_body, cc_addresses=None):
        """
        發送警報郵件
        Args:
            to_addresses (str or list): 收件人
            subject (str): 郵件主旨。
            html_body (str): HTML 格式的郵件內容。
            cc_addresses (str or list, optional): 副本收
        """
        try:
            message = MIMEMultipart("alternative")
            message["From"] = f"{self.sender_name} <{self.sender_email}>"

            if isinstance(to_addresses, str):
                message["To"] = to_addresses
                to_list = [to_addresses]
            else:
                message["To"] = ", ".join(to_addresses)
                to_list = to_addresses

            cc_list = []
            if cc_addresses:
                if isinstance(cc_addresses, str):
                    message["Cc"] = cc_addresses
                    cc_list = [cc_addresses]
                else:
                    message["Cc"] = ", ".join(cc_addresses)
                    cc_list = cc_addresses

            message["Subject"] = subject
            message.attach(MIMEText(html_body, "html", "utf-8"))

            with smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=30) as server:
                server.sendmail(
                    self.sender_email,
                    to_list + cc_list,
                    message.as_string()
                )
            logging.info("✅ 郵件發送成功!")
            return True

        except Exception as e:
            logging.info(f"❌ 郵件發送失敗: {str(e)}")
            return False
