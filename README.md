# ChatHype

**ChatHype** is a desktop application that downloads, processes, and visualizes chat logs for Twitch VODs. It identifies key moments based on chat activity, helping streamers and viewers easily find highlights in recorded streams.

## Features

- **Download VODs and Chat Logs** from Twitch using `twitch-dl.pyz` and `TwitchDownloaderCLI`.
- **Visualize Chat Activity** with adjustable time intervals and thresholds.
- **Highlight Peaks and Valleys** in chat activity to identify exciting moments.
- **Export Highlights** to CSV for easy reference and sharing.

## Requirements

- **Python 3.x**

## Usage

1. **Enter Twitch VOD URL** to download chat logs and videos.
2. **Adjust settings** (time intervals, emote tracking, etc.) to customize highlight detection.
3. Directly open the Twitch VOD at highlights or at the selected timestamp ushing SHIFT+Left-Click
4. **View chat activity graphs** and **export highlights** as CSV for later reference.

## Credits

https://github.com/lay295/TwitchDownloader TwitchDownloaderCLI.exe for chatlog downloading

https://github.com/ihabunek/twitch-dl twitch-dl.pyz for vod downloads

## License

This project is licensed under the MIT License.
