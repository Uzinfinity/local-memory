// Local Memory Brain - Popup Script

document.addEventListener("DOMContentLoaded", () => {
  // Tab switching
  const tabs = document.querySelectorAll(".tab");
  const panels = document.querySelectorAll(".panel");

  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      tabs.forEach((t) => t.classList.remove("active"));
      panels.forEach((p) => p.classList.remove("active"));
      tab.classList.add("active");
      document.getElementById(tab.dataset.panel).classList.add("active");
    });
  });

  // Check server health
  checkHealth();

  // Save button
  document.getElementById("saveBtn").addEventListener("click", saveMemory);

  // Search button
  document.getElementById("searchBtn").addEventListener("click", searchMemory);

  // Enter key handlers
  document.getElementById("memoryText").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && e.metaKey) {
      saveMemory();
    }
  });

  document.getElementById("searchQuery").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      searchMemory();
    }
  });
});

function checkHealth() {
  const statusDiv = document.getElementById("status");
  const statusText = document.getElementById("statusText");
  const dot = statusDiv.querySelector(".dot");

  chrome.runtime.sendMessage({ action: "checkHealth" }, (response) => {
    if (response && response.healthy) {
      statusDiv.classList.remove("offline");
      statusDiv.classList.add("online");
      dot.classList.remove("offline");
      dot.classList.add("online");
      statusText.textContent = "Server online";
      document.getElementById("saveBtn").disabled = false;
      document.getElementById("searchBtn").disabled = false;
    } else {
      statusDiv.classList.remove("online");
      statusDiv.classList.add("offline");
      dot.classList.remove("online");
      dot.classList.add("offline");
      statusText.textContent = "Server offline - run 'brain start'";
      document.getElementById("saveBtn").disabled = true;
      document.getElementById("searchBtn").disabled = true;
    }
  });
}

function saveMemory() {
  const text = document.getElementById("memoryText").value.trim();
  const category = document.getElementById("category").value.trim() || "chrome_manual";
  const messageDiv = document.getElementById("saveMessage");

  if (!text) {
    showMessage(messageDiv, "Please enter something to remember", "error");
    return;
  }

  const btn = document.getElementById("saveBtn");
  btn.disabled = true;
  btn.textContent = "Saving...";

  chrome.runtime.sendMessage(
    { action: "saveMemory", text, category },
    (response) => {
      btn.disabled = false;
      btn.textContent = "Save to Brain";

      if (response && response.success) {
        showMessage(messageDiv, "Memory saved successfully!", "success");
        document.getElementById("memoryText").value = "";
      } else {
        showMessage(
          messageDiv,
          response?.error || "Failed to save memory",
          "error"
        );
      }
    }
  );
}

function searchMemory() {
  const query = document.getElementById("searchQuery").value.trim();
  const resultsDiv = document.getElementById("searchResults");

  if (!query) {
    resultsDiv.innerHTML =
      '<div class="message error">Please enter a search query</div>';
    return;
  }

  const btn = document.getElementById("searchBtn");
  btn.disabled = true;
  btn.textContent = "Searching...";

  chrome.runtime.sendMessage({ action: "searchMemory", query }, (response) => {
    btn.disabled = false;
    btn.textContent = "Search";

    if (response && response.error) {
      resultsDiv.innerHTML = `<div class="message error">${response.error}</div>`;
      return;
    }

    const results = response?.results || [];

    if (results.length === 0) {
      resultsDiv.innerHTML =
        '<div class="message">No memories found</div>';
      return;
    }

    resultsDiv.innerHTML = results
      .map(
        (r) => `
        <div class="result-item">
          <div class="category">${r.metadata?.category || "general"}</div>
          <div class="memory">${escapeHtml(r.memory)}</div>
          <div class="score">Relevance: ${(r.score * 100).toFixed(0)}%</div>
        </div>
      `
      )
      .join("");
  });
}

function showMessage(element, text, type) {
  element.innerHTML = `<div class="message ${type}">${text}</div>`;
  setTimeout(() => {
    element.innerHTML = "";
  }, 3000);
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}
