# ChatHype

**ChatHype** is a desktop application that downloads, processes, and visualizes chat logs for Twitch VODs. It identifies key moments based on chat activity, helping streamers and viewers easily find highlights in recorded streams.

<div align="center">
  <img src="https://i.imgur.com/c2rRfo8.png" alt="ChatHype Main Window" width="45%" style="margin-right: 10px;"/>
  <img src="https://i.imgur.com/8MaEJ3H.png" alt="ChatHype Graph View" width="45%"/>
</div>

## Features

- **Download VODs and Chat Logs** from Twitch using `twitch-dl.pyz` and `TwitchDownloaderCLI`.
- **Visualize Chat Activity** with adjustable time intervals and thresholds.
- **Track Custom Emotes** for increased hype accuracy (different chats might use different emotes when excited).
- **Highlight Peaks and Valleys** in chat activity to identify exciting moments.
- **Export Highlights** to CSV for easy reference and sharing.

## Requirements

- **Python 3.x**

## Usage

1. **Enter Twitch VOD URL** to download chat logs and videos.
2. **Adjust settings** (time intervals, emote tracking, etc.) to customize highlight detection.
3. **Open Twitch VODs** at highlights or at the selected timestamp ushing SHIFT+Left-Click
4. **View chat activity graphs** and **export highlights** as CSV for later reference.


## Credits

This project uses the following third-party tools:

- [**twitch-dl**](https://github.com/ihabunek/twitch-dl) - MIT License. Used for downloading VODs from Twitch.
- [**TwitchDownloaderCLI**](https://github.com/lay295/TwitchDownloader) - GPLv3 License. Used for downloading chat logs from Twitch.

Copies of these licenses are included in the repository.

## License

This project is licensed under the GPLv3: http://www.gnu.org/licenses/gpl-3.0.html
