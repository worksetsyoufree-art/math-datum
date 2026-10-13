(function () {
  "use strict";
  var D = window.__DATA__;
  var S = D.systems;
  var byId = {};
  S.forEach(function (s) { byId[s.id] = s; });
  var $ = function (id) { return document.getElementById(id); };
  var esc = function (t) { return String(t == null ? "" : t).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); };
  var nf = function (v, d) { return v == null ? "—" : Number(v).toLocaleString("ru-RU", { minimumFractionDigits: d, maximumFractionDigits: d }).replace(/ /g, " "); };
  var isOk = function (s) { return s.st === "verified"; };
  var title = function (s) { return s.t; };
  var SRC = { "geoprof.nethouse.ru": "geoprof", "terraingis.ru": "terraingis", fieldworker: "Fieldworker" };

  document.getElementById("built").textContent = "Сборка от " + D.built;
  var nv = S.filter(isOk).length;
  $("sub").textContent = "Подтверждённых систем: " + nv + " из " + S.length + ". Параметры перехода к WGS-84, конвертер и результаты проверок.";

  /* ---------- tabs ---------- */
  var tabs = document.querySelectorAll(".tabs button");
  function showTab(name) {
    tabs.forEach(function (b) { b.setAttribute("aria-selected", String(b.dataset.tab === name)); });
    ["conv", "sys", "dat", "chk"].forEach(function (t) { $("tab-" + t).hidden = t !== name; });
    try { history.replaceState(null, "", "#" + name); } catch (e) { /* file:// */ }
  }
  tabs.forEach(function (b) { b.addEventListener("click", function () { showTab(b.dataset.tab); }); });
  var h = (location.hash || "").slice(1);
  if (["conv", "sys", "dat", "chk"].indexOf(h) >= 0) showTab(h);

  /* ---------- converter ---------- */
  var mode = "fwd";
  function parseCoord(t) {
    t = String(t).trim().replace(",", ".");
    if (!t) return NaN;
    var sign = /^-|[SWЮЗsw]\s*$/.test(t) ? -1 : 1;
    var nums = t.replace(/[^0-9.\s°'′"″:]/g, " ").split(/[\s°'′"″:]+/).filter(Boolean).map(Number);
    if (!nums.length || nums.some(isNaN)) return NaN;
    var v = Math.abs(nums[0]) + (nums[1] || 0) / 60 + (nums[2] || 0) / 3600;
    return sign * v;
  }
  function regionList() {
    var m = {};
    var list = $("showUnv").checked ? S : S.filter(isOk);
    list.forEach(function (s) { var k = s.rc || "—"; m[k] = m[k] || { rc: k, name: s.r || "Без привязки к региону", n: 0 }; m[k].n++; });
    return Object.keys(m).sort().map(function (k) { return m[k]; });
  }
  function fillRegions() {
    var cur = $("region").value;
    $("region").innerHTML = regionList().map(function (r) { return '<option value="' + esc(r.rc) + '">' + esc(r.rc + " — " + r.name + " (" + r.n + ")") + "</option>"; }).join("");
    if (cur && $("region").querySelector('option[value="' + cur + '"]')) $("region").value = cur;
    else $("region").value = $("region").querySelector('option[value="50"]') ? "50" : $("region").options[0].value;
    fillSystems();
  }
  function systemsOfRegion() {
    var rc = $("region").value;
    return S.filter(function (s) { return (s.rc || "—") === rc && ($("showUnv").checked || isOk(s)); });
  }
  function fillSystems(keep) {
    var list = systemsOfRegion();
    var cur = keep || $("system").value;
    $("system").innerHTML = list.map(function (s) {
      return '<option value="' + s.id + '">' + esc((isOk(s) ? "✓ " : "? ") + title(s) + " · ЦМ " + nf(s.g.lon0, 4) + "°") + "</option>";
    }).join("");
    if (cur && byId[cur] && list.indexOf(byId[cur]) >= 0) $("system").value = cur;
    update();
  }
  function cur() { return byId[$("system").value]; }
  function mapinfo(s) {
    var ell = { krass: 3, bessel: 10 }[s.e];
    if (!ell) return null;
    var d = s.d.map(function (v, i) { return v == null ? 0 : v; });
    return '"' + title(s) + '", 8, 9999, ' + ell + ", " + d.map(function (v) { return +v.toFixed(6); }).join(", ") + ", 0, 7, " + +s.g.lon0.toFixed(11) + ", " + +s.g.lat0.toFixed(11) + ", 1, " + s.g.fe + ", " + s.g.fn;
  }
  function badge(s) { return isOk(s) ? '<span class="badge ok">подтверждена</span>' : '<span class="badge warn">неподтверждена</span>'; }
  function info(s) {
    if (!s) { $("sysinfo").innerHTML = "Нет систем для этого региона."; return; }
    var src = s.s.map(function (x) { return SRC[x] || x; }).join(", ");
    var t = badge(s) + " Источники: " + esc(src) + ". Эллипсоид: " + esc(s.e) + ". Ложный восток " + nf(s.g.fe, 3) + ", ложный север " + nf(s.g.fn, 3) + ".";
    if (s.fl.length) t += "<br>⚠ " + s.fl.map(esc).join("<br>⚠ ");
    if (s.ur.length) t += "<br>Причины: " + s.ur.map(esc).join("; ");
    $("sysinfo").innerHTML = t;
  }
  function update() {
    var s = cur();
    info(s);
    $("zones").innerHTML = "";
    var out = $("out");
    if (!s) { out.textContent = ""; return; }
    try {
      if (mode === "fwd") {
        var lat = parseCoord($("lat").value), lon = parseCoord($("lon").value);
        if (isNaN(lat) || isNaN(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 360) { out.textContent = "Введите широту и долготу."; return; }
        var r = proj4("EPSG:4326", s.p4, [lon, lat]);
        var back = proj4(s.p4, "EPSG:4326", r);
        var off = (r[0] - s.g.fe) / 1000;
        out.innerHTML = '<div class="big"><b>X</b> (север) ' + nf(r[1], 3) + " м &nbsp; <b>Y</b> (восток) " + nf(r[0], 3) + " м</div>" +
          '<div class="muted">E = ' + nf(r[0], 3) + ", N = " + nf(r[1], 3) + " · смещение от осевого меридиана " + nf(off, 1) + " км · обратно: " + back[1].toFixed(8) + ", " + back[0].toFixed(8) + "</div>" +
          (Math.abs(off) > 260 ? '<div class="badge warn">точка далеко от осевого меридиана этой зоны</div>' : "");
      } else {
        var x = parseFloat(String($("xin").value).replace(/\s/g, "").replace(",", ".")), y = parseFloat(String($("yin").value).replace(/\s/g, "").replace(",", "."));
        if (isNaN(x) || isNaN(y)) { out.textContent = "Введите X (север) и Y (восток)."; return; }
        var g = proj4(s.p4, "EPSG:4326", [y, x]);
        out.innerHTML = '<div class="big"><b>Широта</b> ' + g[1].toFixed(8) + "° &nbsp; <b>Долгота</b> " + g[0].toFixed(8) + "°</div>" +
          '<div class="muted">WGS-84 (EPSG:4326)</div>';
      }
    } catch (e) { out.textContent = "Ошибка пересчёта: " + e.message; }
  }
  function setMode(m) {
    mode = m;
    $("m-fwd").setAttribute("aria-pressed", String(m === "fwd"));
    $("m-inv").setAttribute("aria-pressed", String(m === "inv"));
    $("in-fwd").hidden = m !== "fwd"; $("in-inv").hidden = m !== "inv";
    update();
  }
  $("m-fwd").onclick = function () { setMode("fwd"); };
  $("m-inv").onclick = function () { setMode("inv"); };
  ["lat", "lon", "xin", "yin"].forEach(function (id) { $(id).addEventListener("input", update); });
  $("region").addEventListener("change", function () { fillSystems(); });
  $("system").addEventListener("change", update);
  $("showUnv").addEventListener("change", fillRegions);
  $("find").onclick = function () {
    var lat = parseCoord($("lat").value), lon = parseCoord($("lon").value);
    if (isNaN(lat) || isNaN(lon)) { $("zones").textContent = "Сначала введите широту и долготу."; return; }
    var rows = systemsOfRegion().map(function (s) {
      var r = proj4("EPSG:4326", s.p4, [lon, lat]);
      return { s: s, off: Math.abs(r[0] - s.g.fe) / 1000 };
    }).sort(function (a, b) { return a.off - b.off; }).slice(0, 6);
    $("zones").innerHTML = "Ближайшие зоны (по расстоянию до осевого меридиана): " + rows.map(function (r) {
      return '<button data-id="' + r.s.id + '">' + esc(title(r.s)) + " — " + nf(r.off, 1) + " км</button>";
    }).join("");
    $("zones").querySelectorAll("button").forEach(function (b) { b.onclick = function () { $("system").value = b.dataset.id; update(); }; });
  };
  function copy(text, btn) {
    if (!text) return;
    var done = function () { var t = btn.textContent; btn.textContent = "Скопировано"; setTimeout(function () { btn.textContent = t; }, 1200); };
    if (navigator.clipboard) navigator.clipboard.writeText(text).then(done, function () { window.prompt("Скопируйте:", text); });
    else window.prompt("Скопируйте:", text);
  }
  $("copy-p4").onclick = function () { var s = cur(); if (s) copy(s.p4, $("copy-p4")); };
  $("copy-mi").onclick = function () { var s = cur(); if (s) copy(mapinfo(s) || "Строка MapInfo доступна только для эллипсоидов Красовского и Бесселя", $("copy-mi")); };

  /* ---------- systems table ---------- */
  var filtered = [];
  function renderTable() {
    var q = $("q").value.trim().toLowerCase(), st = $("f-status").value, src = $("f-src").value;
    filtered = S.filter(function (s) {
      if (st === "verified" && !isOk(s)) return false;
      if (st === "unverified" && isOk(s)) return false;
      if (src && s.s.indexOf(src) < 0) return false;
      if (!q) return true;
      return (s.id + " " + (s.rc || "") + " " + (s.r || "") + " " + s.n.join(" ") + " " + s.g.lon0).toLowerCase().indexOf(q) >= 0;
    });
    $("count").textContent = "Найдено: " + filtered.length;
    var rows = filtered.map(function (s) {
      return '<tr data-id="' + s.id + '"><td>' + s.id + "</td><td>" + esc((s.rc || "—") + " " + (s.r || "")) + "</td><td>" + esc(title(s)) +
        '</td><td class="num">' + nf(s.g.lon0, 4) + '</td><td class="num">' + nf(s.g.fe, 3) + '</td><td class="num">' + nf(s.g.fn, 3) + "</td><td>" +
        esc(s.s.map(function (x) { return SRC[x] || x; }).join(", ")) + "</td><td>" + badge(s) + "</td></tr>";
    });
    $("tbl").tBodies[0].innerHTML = rows.join("");
  }
  $("tbl").tBodies[0].addEventListener("click", function (e) {
    var tr = e.target.closest("tr[data-id]");
    if (!tr) return;
    var nx = tr.nextElementSibling;
    if (nx && nx.classList.contains("detail")) { nx.remove(); return; }
    var s = byId[tr.dataset.id];
    var d = document.createElement("tr");
    d.className = "detail";
    var dv = s.d.map(function (v) { return v == null ? "—" : +v.toFixed(5); }).join(", ");
    d.innerHTML = '<td colspan="8"><div><b>Названия:</b> ' + s.n.map(esc).join("; ") + "</div>" +
      "<div><b>Датум</b> (ΔX, ΔY, ΔZ, ωx, ωy, ωz, m) локальная → WGS-84, ГОСТ-форма: " + esc(dv) + " — " + esc(s.db) + "</div>" +
      "<div><b>PROJ:</b><pre>" + esc(s.p4) + "</pre></div>" +
      (mapinfo(s) ? "<div><b>MapInfo:</b><pre>" + esc(mapinfo(s)) + "</pre></div>" : "") +
      (s.fl.length ? "<div>⚠ " + s.fl.map(esc).join("<br>⚠ ") + "</div>" : "") +
      (s.ur.length ? "<div>Не подтверждена: " + s.ur.map(esc).join("; ") + "</div>" : "") +
      "<div><b>Проверки:</b> " + esc(JSON.stringify(s.ck)) + "</div>" +
      (s.u.length ? "<div><b>Страницы:</b> " + s.u.map(function (u) { return '<a href="' + esc(u) + '" rel="noopener">' + esc(u) + "</a>"; }).join(" · ") + "</div>" : "") +
      '<div class="row"><button class="ghost" data-use="' + s.id + '">Открыть в конвертере</button></div></td>';
    tr.after(d);
    d.querySelector("[data-use]").onclick = function () {
      $("showUnv").checked = !isOk(s) || $("showUnv").checked; fillRegions();
      $("region").value = s.rc || "—"; fillSystems(s.id); showTab("conv");
    };
  });
  ["q", "f-status", "f-src"].forEach(function (id) { $(id).addEventListener("input", renderTable); });
  function download(name, mime, text) {
    var a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type: mime }));
    a.download = name; document.body.appendChild(a); a.click(); a.remove();
  }
  $("dl-json").onclick = function () { download("msk_systems.json", "application/json", JSON.stringify(filtered, null, 1)); };
  $("dl-csv").onclick = function () {
    var q = function (v) { return '"' + String(v == null ? "" : v).replace(/"/g, '""') + '"'; };
    var head = ["id", "region_code", "region", "name", "lon0", "lat0", "false_easting", "false_northing", "ellipsoid", "status", "sources", "proj4"];
    var lines = [head.join(",")].concat(filtered.map(function (s) {
      return [s.id, s.rc, s.r, title(s), s.g.lon0, s.g.lat0, s.g.fe, s.g.fn, s.e, s.st, s.s.join("+"), s.p4].map(q).join(",");
    }));
    download("msk_systems.csv", "text/csv;charset=utf-8", "﻿" + lines.join("\n"));
  };

  /* ---------- datums ---------- */
  $("tbl-dt").tBodies[0].innerHTML = D.transforms.map(function (t) {
    var p = t.to_wgs84_gost_form;
    var ok = /^(verified|corroborated)/.test(t.status);
    return "<tr><td>" + esc(t.code) + "</td><td>" + esc(t.ellipsoid) + "</td>" +
      [0, 1, 2].map(function (i) { return '<td class="num">' + nf(p[i], 3) + "</td>"; }).join("") +
      [3, 4, 5].map(function (i) { return '<td class="num">' + (p[i] == null ? "?" : nf(p[i], 5)) + "</td>"; }).join("") +
      '<td class="num">' + nf(p[6], 4) + '</td><td><span class="badge ' + (ok ? "ok" : "warn") + '">' + esc(t.status.split(":")[0]) + "</span> " +
      esc(t.epsg_match || t.omega_y) + "</td></tr>";
  }).join("");
  $("tbl-fed").tBodies[0].innerHTML = D.federal.map(function (f) {
    return "<tr><td>" + f.epsg + "</td><td>" + esc(f.name) + "</td><td>" + esc(f.datum) + "</td><td>" + esc(f.ellipsoid) + '</td><td class="num">' + nf(f.a, 1) +
      '</td><td class="num">' + nf(f.inv_f, 9) + "</td><td>" + (f.ops.length ? f.ops.length + " (точность до " + Math.min.apply(null, f.ops.map(function (o) { return o.accuracy > 0 ? o.accuracy : 99; })) + " м)" : "нет") + "</td></tr>";
  }).join("");

  /* ---------- checks ---------- */
  (function () {
    var un = S.filter(function (s) { return !isOk(s); });
    var reasons = {};
    un.forEach(function (s) { s.ur.forEach(function (r) { var k = r.replace(/\d+(\.\d+)?/g, "N"); reasons[k] = (reasons[k] || 0) + 1; }); });
    var c = D.checks;
    var h = '<div class="kpi"><div><b>' + S.length + "</b>всего систем</div><div><b>" + nv + "</b>подтверждено</div><div><b>" + un.length + "</b>неподтверждено</div><div><b>" +
      new Set(S.map(function (s) { return s.rc; })).size + "</b>регионов</div></div>";
    h += '<div class="card"><h2>Что считается подтверждённой системой</h2><ul class="plain">' +
      "<li>минимум два независимых источника совпадают по осевому меридиану, ложным координатам и датуму;</li>" +
      "<li>пересчёт WGS-84 → МСК → WGS-84 замыкается (&lt; 5 мм) на контрольных точках региона;</li>" +
      "<li>номер зоны согласован с рядом зон региона (шаг 1,5° / 2° / 3° / 6° от первой зоны);</li>" +
      "<li>столица региона лежит не далее 260 км от осевого меридиана какой-либо зоны региона; у городских систем — свой город в пределах 150 км.</li></ul></div>";
    h += '<div class="card"><h2>Знаки поворотов</h2><p>Параметры ГОСТ/MapInfo переведены в PROJ с инверсией знаков поворотов. Сверка с эталоном EPSG:5044: с инверсией разница <b>' +
      (c.rotation_sign.max_diff_m_flipped_signs * 100).toFixed(3) + " см</b>, без инверсии — <b>" + c.rotation_sign.max_diff_m_unflipped.toFixed(1) + " м</b>.</p></div>";
    h += '<div class="card"><h2>Движок пересчёта</h2><p>Этот сайт считает через proj4js; в CI результат сверяется с PROJ (pyproj) на всех контрольных точках всех систем (<code>tests/proj4_parity.mjs</code>).</p></div>';
    h += '<div class="card"><h2>Почему системы не подтверждены</h2><ul class="plain">' + Object.keys(reasons).sort(function (a, b) { return reasons[b] - reasons[a]; }).map(function (k) { return "<li>" + esc(k) + ": " + reasons[k] + "</li>"; }).join("") + "</ul></div>";
    h += '<div class="card"><h2>Нет данных в открытых источниках</h2><ul class="plain">' + Object.keys(c.missing_regions).map(function (k) { return "<li>" + k + " — " + esc(c.missing_regions[k]) + "</li>"; }).join("") + "<li>новые регионы (ДНР, ЛНР, Запорожская, Херсонская области)</li></ul></div>";
    h += '<div class="card"><h2>Сдвиг федеральных датумов в WGS-84, м</h2><div class="tablewrap" style="margin:0"><table><thead><tr><th>EPSG</th><th>Система</th><th class="num">Москва</th><th class="num">СПб</th><th class="num">Владивосток</th><th class="num">Калининград</th></tr></thead><tbody>' +
      c.federal_shifts.map(function (f) { var v = f.shift_m; return "<tr><td>" + f.epsg + "</td><td>" + esc(f.name) + '</td><td class="num">' + nf(v["Москва"], 1) + '</td><td class="num">' + nf(v["Санкт-Петербург"], 1) + '</td><td class="num">' + nf(v["Владивосток"], 1) + '</td><td class="num">' + nf(v["Калининград"], 1) + "</td></tr>"; }).join("") +
      "</tbody></table></div><p class=\"muted\">Для Pulkovo 1942(58) и (83) в EPSG нет преобразования в WGS 84 (показан 0).</p></div>";
    $("chk").innerHTML = h;
  })();

  fillRegions();
  renderTable();
})();
