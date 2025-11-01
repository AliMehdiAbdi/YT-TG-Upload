# YT-TG-Upload

A Python tool that allows you to download YouTube videos in your preferred quality and automatically upload them to a Telegram channel.

![Python](https://img.shields.io/badge/Python-3.7%2B-blue)
![License](https://img.shields.io/badge/License-MIT-green)

## ✨ Features

- 📋 Lists all available video and audio quality options
- 🎮 User-friendly command-line interface
- 🔒 Support for authenticated YouTube videos via cookies
- 🖼️ Preserves video thumbnails
- 📱 Uploads directly to Telegram channels
- 🧹 Automatic cleanup of downloaded files
- 🎞️ Supports various video container formats (MP4, MKV, WebM)
- 🎵 Supports downloading of entire YouTube playlists

## 📋 Requirements

- Python 3.7 or higher
- Telegram API credentials (API ID, API Hash)
- A Telegram Bot token
- FFmpeg

## 🔧 FFmpeg Installation

FFmpeg is required for video and audio processing. Follow the instructions below to install it on your system.

### Windows

1.  **Download**: Go to the [FFmpeg website](https://ffmpeg.org/download.html) and download the latest Windows build.
2.  **Extract**: Extract the downloaded archive to a directory (e.g., `C:\ffmpeg`).
3.  **Add to PATH**: Add the `bin` directory inside your FFmpeg installation folder (e.g., `C:\ffmpeg\bin`) to your system's PATH environment variable. You can search for "Environment Variables" in Windows, then edit the "Path" variable under "System variables".
4.  **Verify**: Open a new command prompt and type `ffmpeg -version`. If installed correctly, you should see FFmpeg version information.

### macOS

1.  **Homebrew**: The easiest way to install FFmpeg on macOS is using Homebrew. If you don't have Homebrew, install it by following instructions on [brew.sh](https://brew.sh/).
2.  **Install**: Open your terminal and run:
    ```bash
    brew install ffmpeg
    ```
3.  **Verify**: Run `ffmpeg -version` in your terminal to confirm the installation.

### Linux (Debian/Ubuntu)

1.  **Update packages**: Open your terminal and run:
    ```bash
    sudo apt update
    ```
2.  **Install**: Install FFmpeg using apt:
    ```bash
    sudo apt install ffmpeg
    ```
3.  **Verify**: Run `ffmpeg -version` in your terminal to confirm the installation.

### Other Linux Distributions

Refer to your distribution's package manager documentation for FFmpeg installation. For example:

- **Fedora**: `sudo dnf install ffmpeg`
- **Arch Linux**: `sudo pacman -S ffmpeg`

## 🚀 Installation

1. Clone this repository:

   ```bash
   git clone https://github.com/AliMehdiAbdi/YT-TG-Upload.git
   cd YT-TG-Upload
   ```

2. Install the required dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Create a `.env` file in the project directory with your Telegram credentials. You can use `.env.example` as a template, but ensure you create a file named `.env`.
   ```
   TELEGRAM_API_ID=your_api_id
   TELEGRAM_API_HASH=your_api_hash
   TELEGRAM_BOT_TOKEN=your_bot_token
   TELEGRAM_CHANNEL_ID=-100XXXXXXXXXX
   ```

## 🔑 Obtaining Telegram Credentials

1. Visit [my.telegram.org/apps](https://my.telegram.org/apps) and log in with your Telegram account
2. Create a new application to receive your API ID and API Hash
3. Contact [@BotFather](https://t.me/BotFather) on Telegram to create a new bot and receive a bot token
4. Make sure your bot is added as an administrator to the target channel

## 💻 Usage

Run the script from the project root:

```bash
python main.py
```

Follow the interactive prompts:

1. Enter the YouTube URL
2. Optionally provide a path to a Netscape-format cookies file
3. Select from the available video and audio formats
4. Select the desired video container format (MP4, MKV, WebM)
5. Wait for the download and upload to complete

## 🍪 Using Cookies for Private Videos

For private or age-restricted videos, you can use a cookies file:

### Getting Cookies in Netscape Format

#### Chrome:

1. Install the [Get cookies.txt](https://chrome.google.com/webstore/detail/get-cookiestxt/bgaddhkoddajcdgocldbbfleckgcbcid) extension
2. Go to [YouTube](https://www.youtube.com) and make sure you're logged in
3. Click on the extension icon while on YouTube
4. Click "Export" to download the cookies file
5. Save the file in a secure location

#### Firefox:

1. Install the [cookies.txt](https://addons.mozilla.org/en-US/firefox/addon/cookies-txt/) add-on
2. Go to [YouTube](https://www.youtube.com) and make sure you're logged in
3. Click on the add-on icon in your browser toolbar
4. Click "Export" to save the cookies for the current site
5. Save the file in a secure location

#### Using the Cookies File:

1. When prompted by the script, enter the full path to your saved cookies file
2. The cookies will be used to authenticate your YouTube requests
3. Keep your cookies file secure as it contains sensitive session information

## 🛠️ Troubleshooting

- **Error: Required environment variables not set** - Make sure your `.env` file is properly configured
- **Error: Invalid YouTube URL** - Check that the URL is formatted correctly
- **Upload failures** - Ensure the bot has admin privileges in the channel and the channel ID is correct
- **Format ID errors** - Select a format ID from the displayed list

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

Made with ❤️ by **Ali Mehdi** • [![GitHub](https://img.shields.io/badge/GitHub-Profile-blue)](https://github.com/AliMehdiAbdi)
