import "./style.css";

const TOKEN_KEY = "gluekettle_token";
const LABELS = { cold: "冷锅", boiling: "熬煮中", drawn: "已出胶" };
const GAP_LIMIT = 12;

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
  view: "board", // board = 锅位作业台，heat = 火候台（只读）
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

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

function gapText(g) {
  return `与邻锅「${g.neighborCode}」（${g.neighborPeakC}℃）差 ${g.gap}℃`;
}

async function refresh() {
  state.board = await api("/api/board");
  if (state.picked) {
    state.picked = state.board.kettles.find((k) => k.id === state.picked.id) || null;
  }
  if (state.view === "heat") {
    state.heat = await api("/api/heat");
  }
  render();
}

function renderLogin() {
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
    <p class="err">${esc(state.err)}</p>
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
    }
  };
  app.append(box);
}

function renderTopbar() {
  const bar = el(`<header class="topbar">
    <div class="brand">骨巷熬胶坊</div>
    <nav>
      <button data-view="board" class="${state.view === "board" ? "active" : ""}">锅位作业台</button>
      <button data-view="heat" class="${state.view === "heat" ? "active" : ""}">火候台</button>
    </nav>
  </header>`);
  bar.querySelectorAll("[data-view]").forEach((b) => {
    b.onclick = async () => {
      if (state.view === b.dataset.view) return;
      state.view = b.dataset.view;
      state.err = "";
      await refresh();
    };
  });
  return bar;
}

function gapLine(g) {
  const cls = g.overLimit ? "gap over" : "gap ok";
  const verdict = g.overLimit ? `超阈值 ${GAP_LIMIT}℃，挡住` : `未超阈值 ${GAP_LIMIT}℃`;
  return `<li class="${cls}">${esc(gapText(g))} · ${esc(verdict)}</li>`;
}

function renderBoard(box) {
  box.append(el(`<p class="sub">${esc(state.board.alley)} · 点锅登记峰值；开火与相邻熬煮锅比峰值（阈值 ${GAP_LIMIT}℃）；出胶须最近峰值 ≥ 90℃</p>`));
  const row = el(`<div class="row"></div>`);
  state.board.kettles.forEach((k) => {
    const btn = el(`<button class="kettle ${k.status}">
      <strong>${esc(k.code)}</strong>
      <span>${LABELS[k.status]}</span>
      <span class="peak">${k.latestPeakC ?? "—"}℃</span>
    </button>`);
    btn.onclick = () => {
      state.picked = k;
      render();
    };
    row.append(btn);
  });
  box.append(row);

  const d = el(`<section class="drawer"></section>`);
  if (state.picked) {
    const k = state.picked;
    const gaps = (k.neighborGaps || []).map(gapLine).join("");
    d.innerHTML = `<h3>${esc(k.code)} · ${LABELS[k.status]}</h3>
      <p>最近峰值：${k.latestPeakC ?? "无"} ℃ · ${k.cookCount} 次记录</p>
      <ul class="gaps">${gaps || `<li class="gap none">无相邻熬煮锅，开火不比火候</li>`}</ul>
      <input id="peak" value="${esc(state.peak)}" />
      <button id="log">登记峰值</button>
      <div class="status-btns">
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
  } else {
    d.innerHTML = `<p class="hint">点上方锅位查看详情并登记。</p>`;
  }
  box.append(d);
}

function renderHeat(box) {
  box.append(el(`<p class="sub">只读火候台 · 按坊列出各锅峰值与相邻熬煮锅差值（阈值 ${GAP_LIMIT}℃）</p>`));
  (state.heat?.workshops || []).forEach((ws) => {
    const rows = ws.kettles
      .map((k) => {
        const gaps = (k.neighborGaps || []);
        const gapHtml = gaps.length
          ? gaps
              .map((g) => {
                const cls = g.overLimit ? "over" : "ok";
                return `<span class="heat-gap ${cls}">${esc(g.neighborCode)} ${g.neighborPeakC}℃ · 差 ${g.gap}℃${g.overLimit ? " ✕" : " ✓"}</span>`;
              })
              .join("")
          : `<span class="hint">无相邻熬煮锅</span>`;
        return `<tr>
          <td>${k.bench}</td>
          <td>${esc(k.code)}</td>
          <td><span class="badge ${k.status}">${LABELS[k.status] || esc(k.status)}</span></td>
          <td class="num">${k.latestPeakC ?? "—"}</td>
          <td><div class="gap-cell">${gapHtml}</div></td>
        </tr>`;
      })
      .join("");
    const sec = el(`<section class="heat-shop">
      <h2>${esc(ws.workshop)} <small>${esc(ws.alley)}</small></h2>
      <table>
        <thead><tr><th>锅位</th><th>锅号</th><th>状态</th><th>最近峰值℃</th><th>与相邻熬煮锅差值</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </section>`);
    box.append(sec);
  });
}

function render() {
  app.innerHTML = "";
  if (!state.ready) {
    renderLogin();
    return;
  }
  if (!state.board) {
    app.append(el(`<div class="wrap">${esc(state.err) || "装载锅位…"}</div>`));
    return;
  }
  const wrap = el(`<div class="wrap"></div>`);
  wrap.append(renderTopbar());
  const view = el(`<div class="view"></div>`);
  if (state.view === "heat") {
    if (!state.heat) {
      view.append(el(`<p>装载火候台…</p>`));
    } else {
      renderHeat(view);
    }
  } else {
    renderBoard(view);
  }
  wrap.append(view);
  if (state.err) wrap.append(el(`<p class="err">${esc(state.err)}</p>`));
  app.append(wrap);
}

if (state.ready) {
  refresh().catch((e) => {
    state.err = e.message;
    render();
  });
} else {
  render();
}
