/* 画面の中の確かめ・入力の窓(ブラウザ版とデスクトップ版で同じ見た目)。
 * デスクトップ版(WebView)では confirm()/prompt() が出ない・止まることがあるので使わない。
 *   await UI.confirm("消します。よろしいですか？")  → true / false
 *   await UI.prompt("名前", "既定")               → 文字 / null(やめる)
 * あわせて、デスクトップ版の窓の × を受ける口(ALGDesktop)を持つ。
 */
"use strict";
(function (global) {
  function box(message, withInput, value, password) {
    return new Promise((resolve) => {
      const wrap = document.createElement("div");
      wrap.className = "uidlg";
      wrap.setAttribute("role", "dialog");
      wrap.setAttribute("aria-modal", "true");
      wrap.innerHTML = `<div class="uidlg__box"><p class="uidlg__msg"></p>
        ${withInput ? `<input class="uidlg__in" type="${password ? "password" : "text"}">` : ""}
        <div class="uidlg__btns"><button class="btn" type="button" data-no>やめる</button>
        <button class="btn btn--primary" type="button" data-yes>OK</button></div></div>`;
      wrap.querySelector(".uidlg__msg").textContent = message;
      const input = wrap.querySelector(".uidlg__in");
      if (input) input.value = value || "";
      document.body.appendChild(wrap);
      const done = (ok) => { wrap.remove(); document.removeEventListener("keydown", key, true); resolve(withInput ? (ok ? input.value : null) : ok); };
      const key = (e) => {
        if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); done(false); }
        if (e.key === "Enter" && (input || document.activeElement === wrap.querySelector("[data-yes]"))) { e.preventDefault(); done(true); }
      };
      document.addEventListener("keydown", key, true);
      wrap.querySelector("[data-no]").onclick = () => done(false);
      wrap.querySelector("[data-yes]").onclick = () => done(true);
      (input || wrap.querySelector("[data-yes]")).focus();
    });
  }
  const UI = {
    confirm: (message) => box(message, false),
    prompt: (message, value, password) => box(message, true, value, password),
  };

  /* デスクトップ版: 窓の × を押すと外枠がここを呼ぶ。保存していない変更があれば訊く */
  const tauri = () => global.__TAURI__ && global.__TAURI__.core;
  const ALGDesktop = {
    isDesktop: () => !!tauri(),
    hasUnsaved: () => false,          // 画面ごとに差し替える
    async closeRequested() {
      const t = tauri();
      if (!t) return;
      await t.invoke("close_ack");    // 受けた印(届かなければ外枠がそのまま閉じる)
      if (ALGDesktop.hasUnsaved() && !(await UI.confirm("保存していない変更があります。保存せずに終了しますか？"))) return;
      await t.invoke("quit");
    },
  };
  global.UI = UI;
  global.ALGDesktop = ALGDesktop;
})(window);
