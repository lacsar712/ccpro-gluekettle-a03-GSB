import "./style.css";

const TOKEN_KEY = "gluekettle_token";
const LABELS = { cold: "冷锅", boiling: "熬煮中", drawn: "已出胶" };

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.body) headers["Content-Type"] = "application/json";
  const t = localStorage.getItem(TOKEN_KEY);
  if (t) headers.Authorization = `Bearer ${t}`;
  const res = await fetch(path, { ...options, headers });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "请求失败");
  return data;
}

const app = document.getElementById("app");
const state = {
  ready: Boolean(localStorage.getItem(TOKEN_KEY)),
  view: "board",
  board: null,
  heat: null,
  picked: null,
  peak: "96",
  err: "",
  username: "admin",
  password: "123456",
};

function el(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

async function refresh() {
  state.board = await api("/api/board");
  if (state.picked) {
    state.picked = state.board.kettles.find((k) => k.id === state.picked.id) || state.board.kettles[0];
  }
  render();
}

async function refreshHeat() {
  state.heat = await api("/api/heat");
}

function navHtml() {
  return `<nav class="top">
    <span class="brand">骨巷熬胶坊</span>
    <button data-v="board" class="${state.view === "board" ? "on" : ""}">锅位作业台</button>
    <button data-v="heat" class="${state.view === "heat" ? "on" : ""}">火候台</button>
  </nav>`;
}

function bindNav(box) {
  box.querySelectorAll("nav.top [data-v]").forEach((b) => {
    b.onclick = async () => {
      if (state.view === b.dataset.v) return;
      state.view = b.dataset.v;
      state.err = "";
      try {
        if (state.view === "heat") await refreshHeat();
        else await refresh();
      } catch (ex) {
        state.err = ex.message;
      }
      render();
    };
  });
}

function heatHtml() {
  if (!state.heat) return `<p>装载火候…</p>`;
  return state.heat.workshops
    .map(
      (w) => `<section class="shop">
      <h2>${w.workshop} · ${w.alley}</h2>
      <table class="heat">
        <thead>
          <tr><th>锅位</th><th>状态</th><th>最近峰值 ℃</th><th>与熬煮邻锅差值 ℃</th></tr>
        </thead>
        <tbody>
          ${w.kettles
            .map(
              (k) => `<tr>
            <td>${k.code}</td>
            <td><span class="chip ${k.status}">${LABELS[k.status] || k.status}</span></td>
            <td>${k.latestPeakC ?? "—"}</td>
            <td>${k.diffC ?? "—"}</td>
          </tr>`
            )
            .join("")}
        </tbody>
      </table>
    </section>`
    )
    .join("");
}

function render() {
  app.innerHTML = "";
  if (!state.ready) {
    const box = el(`<div class="wrap">
      <h1>骨巷熬胶坊</h1>
      <p>一排熬锅作业台，原生页面，无前端框架。</p>
      <form autocomplete="off">
        <label>用户名
          <input name="u" autocomplete="off" value="${state.username}" />
        </label>
        <label>密码
          <input name="p" type="password" autocomplete="off" value="${state.password}" />
        </label>
        <p class="hint">已预填 admin / 123456，另有 worker / 123456</p>
        <button>登录</button>
      </form>
      <p class="err">${state.err}</p>
    </div>`);
    box.querySelector("form").onsubmit = async (e) => {
      e.preventDefault();
      state.err = "";
      try {
        const data = await api("/api/auth/login", {
          method: "POST",
          body: JSON.stringify({
            username: box.querySelector("[name=u]").value,
            password: box.querySelector("[name=p]").value,
          }),
        });
        localStorage.setItem(TOKEN_KEY, data.access_token);
        state.ready = true;
        await refresh();
      } catch (ex) {
        state.err = ex.message;
        render();
        return;
      }
      render();
    };
    app.append(box);
    return;
  }
  if (state.view === "heat") {
    const box = el(`<div class="wrap">
      ${navHtml()}
      <h1>火候台</h1>
      <p>只读专页 · 按坊列出各锅最近峰值与对邻熬煮锅的差值（上限 12℃）</p>
      ${heatHtml()}
      <p class="err">${state.err}</p>
    </div>`);
    bindNav(box);
    app.append(box);
    return;
  }
  if (!state.board) {
    app.append(el(`<div class="wrap">${navHtml()}${state.err || "装载锅位…"}</div>`));
    bindNav(app.querySelector(".wrap"));
    return;
  }
  const box = el(`<div class="wrap">
    ${navHtml()}
    <h1>${state.board.workshop}</h1>
    <p>${state.board.alley} · 点锅登记峰值；出胶须最近峰值 ≥ 90℃；改熬煮中须与邻熬煮锅峰值差 ≤ 12℃</p>
    <div class="row"></div>
    <section class="drawer"></section>
    <p class="err">${state.err}</p>
  </div>`);
  bindNav(box);
  const row = box.querySelector(".row");
  state.board.kettles.forEach((k) => {
    const btn = el(`<button class="kettle ${k.status}"><strong>${k.code}</strong><span>${LABELS[k.status]}</span></button>`);
    btn.onclick = () => {
      state.picked = k;
      state.err = "";
      render();
    };
    row.append(btn);
  });
  if (state.picked) {
    const d = box.querySelector(".drawer");
    d.innerHTML = `<h3>${state.picked.code} · ${LABELS[state.picked.status]}</h3>
      <p>最近峰值：${state.picked.latestPeakC ?? "无"} ℃ · ${state.picked.cookCount} 次</p>
      <input id="peak" value="${state.peak}" />
      <button id="log">登记峰值</button>
      <div>
        <button data-s="cold">冷锅</button>
        <button data-s="boiling">熬煮中</button>
        <button data-s="drawn">已出胶</button>
      </div>`;
    d.querySelector("#log").onclick = async () => {
      state.err = "";
      state.peak = d.querySelector("#peak").value;
      try {
        state.picked = await api(`/api/kettles/${state.picked.id}/cooks`, {
          method: "POST",
          body: JSON.stringify({ peakTempC: Number(state.peak) }),
        });
        await refresh();
      } catch (ex) {
        state.err = ex.message;
        render();
      }
    };
    d.querySelectorAll("[data-s]").forEach((b) => {
      if (b.dataset.s === state.picked.status) b.disabled = true;
      b.onclick = async () => {
        state.err = "";
        try {
          state.picked = await api(`/api/kettles/${state.picked.id}/status`, {
            method: "POST",
            body: JSON.stringify({ status: b.dataset.s }),
          });
          await refresh();
        } catch (ex) {
          state.err = ex.message;
          render();
        }
      };
    });
  }
  app.append(box);
}

if (state.ready) {
  refresh().catch((e) => {
    state.err = e.message;
    render();
  });
} else {
  render();
}
