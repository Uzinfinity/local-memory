// Local Memory Brain - Chrome Extension Background Script

const API_URL = "http://localhost:8000";

// Create context menu on install
chrome.runtime.onInstalled.addListener(() => {
  // Right-click menu for selected text
  chrome.contextMenus.create({
    id: "saveToMemory",
    title: "Save to Local Brain",
    contexts: ["selection"]
  });

  // Right-click menu for page (save page summary)
  chrome.contextMenus.create({
    id: "savePageToMemory",
    title: "Save page title to Local Brain",
    contexts: ["page"]
  });

  console.log("Local Memory Brain extension installed");
});

// Handle context menu clicks
chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === "saveToMemory" && info.selectionText) {
    saveToMemory(info.selectionText, "chrome_selection", tab);
  } else if (info.menuItemId === "savePageToMemory") {
    const pageInfo = `Page: ${tab.title}\nURL: ${tab.url}`;
    saveToMemory(pageInfo, "chrome_page", tab);
  }
});

// Save to local memory API
async function saveToMemory(text, category, tab) {
  try {
    const response = await fetch(`${API_URL}/add`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        text: text,
        category: category,
        source: "chrome_extension"
      })
    });

    if (response.ok) {
      showNotification("Memory Saved", text.substring(0, 50) + "...");
      // Show a brief visual confirmation
      if (tab && tab.id) {
        try {
          chrome.scripting.executeScript({
            target: { tabId: tab.id },
            func: showSaveConfirmation
          });
        } catch (e) {
          // Ignore errors for pages where we can't inject scripts
        }
      }
    } else {
      const error = await response.text();
      showNotification("Error", `Failed to save: ${error}`);
    }
  } catch (error) {
    if (error.message.includes("Failed to fetch")) {
      showNotification("Server Offline", "Run 'brain start' in terminal");
    } else {
      showNotification("Error", error.message);
    }
  }
}

// Show notification
function showNotification(title, message) {
  chrome.notifications.create({
    type: "basic",
    iconUrl: "icons/icon48.png",
    title: title,
    message: message
  });
}

// Injected function to show visual confirmation
function showSaveConfirmation() {
  const div = document.createElement("div");
  div.innerHTML = "Saved to Local Brain!";
  div.style.cssText = `
    position: fixed;
    top: 20px;
    right: 20px;
    background: #10B981;
    color: white;
    padding: 12px 20px;
    border-radius: 8px;
    font-family: -apple-system, BlinkMacSystemFont, sans-serif;
    font-size: 14px;
    z-index: 999999;
    box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    animation: slideIn 0.3s ease-out;
  `;
  document.body.appendChild(div);

  setTimeout(() => {
    div.style.opacity = "0";
    div.style.transition = "opacity 0.3s";
    setTimeout(() => div.remove(), 300);
  }, 2000);
}

// Listen for messages from popup
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === "saveMemory") {
    saveToMemory(request.text, request.category || "chrome_manual", null)
      .then(() => sendResponse({ success: true }))
      .catch((error) => sendResponse({ success: false, error: error.message }));
    return true; // Keep channel open for async response
  }

  if (request.action === "searchMemory") {
    fetch(`${API_URL}/search?q=${encodeURIComponent(request.query)}&limit=5`)
      .then((response) => response.json())
      .then((data) => sendResponse(data))
      .catch((error) => sendResponse({ error: error.message }));
    return true;
  }

  if (request.action === "checkHealth") {
    fetch(`${API_URL}/health`)
      .then((response) => response.json())
      .then((data) => sendResponse({ healthy: true, data }))
      .catch(() => sendResponse({ healthy: false }));
    return true;
  }
});
