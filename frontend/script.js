const API_BASE = "http://localhost:5000/api";

const profileSelect = document.getElementById("profile-select");
const queryInput = document.getElementById("query-input");
const recommendBtn = document.getElementById("recommend-btn");
const coldStartBtn = document.getElementById("cold-start-btn");
const statusEl = document.getElementById("status");
const parsedPrefsEl = document.getElementById("parsed-prefs");
const parsedPrefsContent = document.getElementById("parsed-prefs-content");
const resultsEl = document.getElementById("results");

async function loadProfiles() {
  try {
    const res = await fetch(`${API_BASE}/profiles`);
    const profiles = await res.json();
    profiles.forEach(p => {
      const opt = document.createElement("option");
      opt.value = p.id;
      opt.textContent = p.name;
      profileSelect.appendChild(opt);
    });
  } catch (e) {
    statusEl.textContent = "Could not load sample profiles — is the Flask backend running on port 5000?";
  }
}

profileSelect.addEventListener("change", () => {
  const id = profileSelect.value;
  if (!id) return;
  fetch(`${API_BASE}/profiles`)
    .then(r => r.json())
    .then(profiles => {
      const match = profiles.find(p => p.id === id);
      if (match) queryInput.value = match.query;
    });
});

function formatPrefs(prefs) {
  const lines = [];
  if (prefs.category) lines.push(`category: ${prefs.category}`);
  if (prefs.budget_max) lines.push(`budget: up to ₹${Number(prefs.budget_max).toLocaleString("en-IN")}`);
  if (prefs.min_ram_gb) lines.push(`min RAM: ${prefs.min_ram_gb}GB`);
  if (prefs.min_storage_gb) lines.push(`min storage: ${prefs.min_storage_gb}GB`);
  if (prefs.min_battery) lines.push(`min battery: ${prefs.min_battery}`);
  if (prefs.min_camera_mp) lines.push(`min camera: ${prefs.min_camera_mp}MP`);
  if (prefs.priorities && prefs.priorities.length) lines.push(`priorities: ${prefs.priorities.join(", ")}`);
  if (prefs.preferred_brands && prefs.preferred_brands.length) lines.push(`preferred brands: ${prefs.preferred_brands.join(", ")}`);
  return lines.length ? lines.join("\n") : "no specific preferences detected";
}

async function runRecommendation(payload) {
  resultsEl.innerHTML = "";
  parsedPrefsEl.open = false;
  parsedPrefsEl.style.display = "none";
  statusEl.textContent = "Thinking — calling the local Mistral model, this can take a few seconds…";

  try {
    const res = await fetch(`${API_BASE}/recommend`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);

    if (data.mode === "cold_start") {
      statusEl.textContent = "";
      resultsEl.innerHTML = `<div class="cold-start-note">No preferences given yet, so these are the catalog's top-rated picks across categories. Type a request above for a personalized match.</div>`;
    } else {
      statusEl.textContent = "";
      if (data.parsed_preferences) {
        parsedPrefsEl.style.display = "block";
        parsedPrefsContent.textContent = formatPrefs(data.parsed_preferences);
      }
    }

    renderResults(data.recommendations);
  } catch (e) {
    statusEl.textContent = "Error: " + e.message;
  }
}

function renderResults(recommendations) {
  recommendations.forEach(rec => {
    const p = rec.product;
    const card = document.createElement("div");
    card.className = "card";

    const breakdownHtml = Object.entries(rec.score_breakdown)
      .map(([k, v]) => `<span>${k.replace(/_/g, " ")}: <b>${v}</b></span>`)
      .join("");

    card.innerHTML = `
      <div class="tag">${rec.match_percent}% match</div>
      <div class="card-top">
        <h3>${p.name}</h3>
      </div>
      <div class="meta">${p.brand} · ₹${p.price.toLocaleString("en-IN")} · ${p.category}</div>
      <p class="explanation">${rec.explanation}</p>
      <hr class="divider">
      <div class="breakdown">${breakdownHtml}</div>
    `;
    resultsEl.appendChild(card);
  });
}

recommendBtn.addEventListener("click", () => {
  const query = queryInput.value.trim();
  if (!query) {
    statusEl.textContent = "Type a request or pick a sample profile first.";
    return;
  }
  runRecommendation({ query });
});

coldStartBtn.addEventListener("click", () => {
  queryInput.value = "";
  runRecommendation({ query: "" });
});

loadProfiles();


// const API_BASE = "http://localhost:5000/api";

// const profileSelect = document.getElementById("profile-select");
// const queryInput = document.getElementById("query-input");
// const recommendBtn = document.getElementById("recommend-btn");
// const coldStartBtn = document.getElementById("cold-start-btn");
// const statusEl = document.getElementById("status");
// const parsedPrefsEl = document.getElementById("parsed-prefs");
// const parsedPrefsContent = document.getElementById("parsed-prefs-content");
// const resultsEl = document.getElementById("results");

// async function loadProfiles() {
//   try {
//     const res = await fetch(`${API_BASE}/profiles`);
//     const profiles = await res.json();
//     profiles.forEach(p => {
//       const opt = document.createElement("option");
//       opt.value = p.id;
//       opt.textContent = p.name;
//       profileSelect.appendChild(opt);
//     });
//   } catch (e) {
//     statusEl.textContent = "Could not load sample profiles — is the Flask backend running on port 5000?";
//   }
// }

// profileSelect.addEventListener("change", () => {
//   const id = profileSelect.value;
//   if (!id) return;
//   fetch(`${API_BASE}/profiles`)
//     .then(r => r.json())
//     .then(profiles => {
//       const match = profiles.find(p => p.id === id);
//       if (match) queryInput.value = match.query;
//     });
// });

// function formatPrefs(prefs) {
//   const lines = [];
//   if (prefs.category) lines.push(`category: ${prefs.category}`);
//   if (prefs.budget_max) lines.push(`budget: up to ₹${Number(prefs.budget_max).toLocaleString("en-IN")}`);
//   if (prefs.min_ram_gb) lines.push(`min RAM: ${prefs.min_ram_gb}GB`);
//   if (prefs.min_storage_gb) lines.push(`min storage: ${prefs.min_storage_gb}GB`);
//   if (prefs.min_battery) lines.push(`min battery: ${prefs.min_battery}`);
//   if (prefs.min_camera_mp) lines.push(`min camera: ${prefs.min_camera_mp}MP`);
//   if (prefs.priorities && prefs.priorities.length) lines.push(`priorities: ${prefs.priorities.join(", ")}`);
//   if (prefs.preferred_brands && prefs.preferred_brands.length) lines.push(`preferred brands: ${prefs.preferred_brands.join(", ")}`);
//   return lines.length ? lines.join("\n") : "no specific preferences detected";
// }

// async function runRecommendation(payload) {
//   resultsEl.innerHTML = "";
//   parsedPrefsEl.open = false;
//   parsedPrefsEl.style.display = "none";
//   statusEl.textContent = "Thinking — calling the local Mistral model, this can take a few seconds…";

//   try {
//     const res = await fetch(`${API_BASE}/recommend`, {
//       method: "POST",
//       headers: { "Content-Type": "application/json" },
//       body: JSON.stringify(payload),
//     });
//     const data = await res.json();
//     if (data.error) throw new Error(data.error);

//     if (data.mode === "cold_start") {
//       statusEl.textContent = "";
//       resultsEl.innerHTML = `<div class="cold-start-note">No preferences given yet, so these are the catalog's top-rated picks across categories. Type a request above for a personalized match.</div>`;
//     } else {
//       statusEl.textContent = "";
//       if (data.parsed_preferences) {
//         parsedPrefsEl.style.display = "block";
//         parsedPrefsContent.textContent = formatPrefs(data.parsed_preferences);
//       }
//     }

//     renderResults(data.recommendations);
//   } catch (e) {
//     statusEl.textContent = "Error: " + e.message;
//   }
// }

// function renderResults(recommendations) {
//   recommendations.forEach(rec => {
//     const p = rec.product;
//     const card = document.createElement("div");
//     card.className = "card";

//     const breakdownHtml = Object.entries(rec.score_breakdown)
//       .map(([k, v]) => `<span>${k.replace(/_/g, " ")}: <b>${v}</b></span>`)
//       .join("");

//     card.innerHTML = `
//       <div class="tag">${rec.match_percent}% match</div>
//       <div class="card-top">
//         <h3>${p.name}</h3>
//       </div>
//       <div class="meta">${p.brand} · ₹${p.price.toLocaleString("en-IN")} · ${p.category}</div>
//       <p class="explanation">${rec.explanation}</p>
//       <hr class="divider">
//       <div class="breakdown">${breakdownHtml}</div>
//     `;
//     resultsEl.appendChild(card);
//   });
// }

// recommendBtn.addEventListener("click", () => {
//   const query = queryInput.value.trim();
//   if (!query) {
//     statusEl.textContent = "Type a request or pick a sample profile first.";
//     return;
//   }
//   runRecommendation({ query });
// });

// coldStartBtn.addEventListener("click", () => {
//   queryInput.value = "";
//   runRecommendation({ query: "" });
// });

// loadProfiles();
