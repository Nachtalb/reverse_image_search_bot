import logging

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

TELEGRAM_API_TOKEN = "YOUR_API_TOKEN"

UPLOADER = {
    "uploader": "local",  # What uploader to use 'local' or 'ssh'
    "url": "YOUR_DOMAIN_FILES_DIR",
    "configuration": {
        "host": "YOUR_HOST_IP",
        "user": "YOUR_USERNAME",
        "password": "YOUR_PASSWORD",  # If the server does only accepts ssh key login this must be the ssh password
        "upload_dir": "HOST_UPLOAD_DIRECTORY",
        "key_filename": "PATH_TO_PUBLIC_SSH_KEY",  # This is not mandatory but some server configurations require it
    },
}

ADMIN_IDS = []

SAUCENAO_API = ""  # SauceNAO api key https://saucenao.com/user.php?page=search-api

MODE = {
    "active": "webhook",  # or polling
    "configuration": {
        "listen": "127.0.0.1",
        "port": 5020,
        "url_path": "reverse_image_search",
        "webhook_url": "https://EXAMPLE.COM/reverse_image_search",
    },
}
