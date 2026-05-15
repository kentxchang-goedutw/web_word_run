# 🍓 可愛網頁跑馬燈 (Cute Web Marquee)

這是一款專為網頁設計的 Chrome 擴充功能，可以將儲存在 Google 試算表（透過 Google Apps Script）中的文字，以繽紛、可愛的跑馬燈形式顯示在當前的網頁上。適合用於活動、教學或個人化網頁裝飾。

> 💡 **提示**：本專案同時包含一個**獨立網頁版**（`可愛跑馬燈控制中心.html`），如果您不想安裝擴充功能，也可以直接使用該 HTML 檔案。

## ✨ 特色功能

- **雲端同步**：串接 Google Apps Script (GAS)，隨時更新跑馬燈內容。
- **高度自定義**：可自由調整文字大小、顯示速度、重複次數。
- **隨機美感**：支援多色調色盤，文字顏色隨機切換。
- **Shadow DOM 技術**：採用 Shadow DOM 封裝樣式，不會干擾原網頁的 CSS 佈局。
- **一鍵清理**：支援從擴充功能直接清空雲端試算表資料。
- **訪客發文**：內建訪客發文網址產生器，方便他人投稿文字。

## 🛠️ 安裝方式

1. **下載原始碼**：下載本專案的所有檔案（或 Clone 此儲存庫）。
2. **開啟擴充功能管理面**：在 Chrome 網址列輸入 `chrome://extensions/` 並按下 Enter。
3. **啟用開發者模式**：勾選頁面右上角的「**開發者模式**」。
4. **載入擴充功能**：點擊左上角的「**載入解壓縮擴充功能**」，選擇本專案的資料夾（即包含 `manifest.json` 的資料夾）。
5. **固定擴充功能**：點擊瀏覽器工具列的拼圖圖示，將「可愛網頁跑馬燈」固定在工具列上以便使用。

## 🚀 使用說明

### 1. 設定 Google Apps Script (GAS) 後端

您需要建立一個 Google Apps Script 作為資料中繼站：

1. 前往 [Google Apps Script](https://script.google.com/) 並建立新專案。
2. 貼入下方的 GAS 程式碼並存檔：
   ```javascript
   function getSheet() {
     const ss = SpreadsheetApp.getActiveSpreadsheet();
     let sheet = ss.getSheetByName("跑馬燈資料");
     if (!sheet) {
       sheet = ss.insertSheet("跑馬燈資料");
       sheet.appendRow(["時間", "內容"]);
       sheet.getRange("1:1").setFontWeight("bold").setBackground("#ffe4e6");
     }
     return sheet;
   }

   function doGet(e) {
     const sheet = getSheet();
     const data = sheet.getDataRange().getValues();
     data.shift(); // 移除標題
     const result = data.map(row => ({ "時間": row[0], "內容": row[1] }));
     
     const json = JSON.stringify(result);
     return ContentService.createTextOutput(json).setMimeType(ContentService.MimeType.JSON);
   }

   function doPost(e) {
     const sheet = getSheet();
     const params = JSON.parse(e.postData.contents);
     
     if (params.action === "clear") {
       if (sheet.getLastRow() > 1) {
         sheet.getRange(2, 1, sheet.getLastRow() - 1, 2).clearContent();
       }
       return ContentService.createTextOutput("cleared");
     }

     sheet.appendRow([new Date(), params.content]);
     return ContentService.createTextOutput("success");
   }
   ```
3. 點擊「**部署**」 > 「**新部署**」。
4. 類型選擇「**網頁應用程式**」。
5. 「誰有權存取」務必選擇「**任何人**」。
6. 部署後，複製產生的「**網頁應用程式 URL**」。

### 2. 設定擴充功能

1. 點擊 Chrome 工具列上的「可愛網頁跑馬燈」圖示。
2. 在「**GAS Web App 網址**」欄位貼上剛才複製的網址。
3. 勾選「**啟用跑馬燈功能**」。
4. 根據喜好調整文字大小、速度、重複次數與顏色。
5. 點擊「**儲存並套用 ✨**」。
6. 重新整理您想要顯示跑馬燈的網頁，即可看到效果！

## 🎨 授權資訊

本工具由 [阿剛老師](https://kentxchang.blogspot.tw) 開發。
採用 **[CC BY-NC-SA 4.0 授權](https://creativecommons.org/licenses/by-nc-sa/4.0/deed.zh_TW)** (姓名標示-非商業性-相同方式分享)。
