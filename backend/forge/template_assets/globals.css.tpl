:root {font-family:Arial,"Noto Sans TC",sans-serif;color:#253c35;background:#f5f3ed;font-synthesis:none}
* {box-sizing:border-box} body {margin:0} button,input {font:inherit} button {cursor:pointer}
main {--accent:#35634f;max-width:920px;margin:auto;padding:36px 32px 60px}
main[data-theme=indigo] {--accent:#504b86} main[data-theme=amber] {--accent:#925f23}
header {display:flex;align-items:center;justify-content:space-between;padding-bottom:28px;border-bottom:1px solid #d9ded4}
.eyebrow {font-size:11px;letter-spacing:2px;font-weight:700;color:#61766b}.mark {font-size:28px;color:var(--accent)}
.intro {position:relative;padding:56px 0 40px}.intro h1 {font-size:clamp(32px,5vw,52px);font-weight:500;letter-spacing:-1px;margin:14px 0}
.intro>p:not(.eyebrow) {color:#718076;line-height:1.8;max-width:590px}.stats {display:flex;align-items:center;gap:14px;margin-top:24px}
.stats strong {font-size:32px;font-weight:500}.stats span {font-size:13px;color:#718076}
.workspace {padding:28px;background:#fffdf7;border:1px solid #e1e4d8;border-radius:20px;box-shadow:0 15px 40px #26362a06}
form {display:flex;gap:12px} form input {min-width:0;flex:1;padding:16px;border:1px solid #d7ded2;border-radius:10px;background:#fff}
form button {border:0;color:white;background:var(--accent);border-radius:10px;padding:0 20px;white-space:nowrap}
button:disabled {opacity:.5;cursor:default} button:focus-visible,input:focus-visible {outline:3px solid #b0cba5;outline-offset:3px}
form button span {margin-left:12px} nav {display:flex;gap:12px;border-bottom:1px solid #e4e8dd;padding:26px 0 14px}
nav button {border:0;padding:8px 13px;border-radius:20px;background:none;color:#728071;font-size:13px}
nav button[aria-pressed=true] {color:var(--accent);background:#edf2e8} ul {list-style:none;padding:0;margin:0}
li {display:flex;align-items:center;gap:14px;padding:20px 2px;border-bottom:1px solid #edf0e7}
li input {accent-color:var(--accent);width:19px;height:19px} li span {flex:1;overflow-wrap:anywhere;line-height:1.6}
li.done span {text-decoration:line-through;color:#879286}.delete {border:0;background:none;color:#8a9588;font-size:24px;padding:2px 8px}
.empty {text-align:center;padding:46px 12px}.empty>span {font-size:52px;color:#91a789}.empty h2 {font-size:17px;font-weight:500}
.empty p,footer {font-size:12px;color:#899384}footer {text-align:center;padding-top:24px}.error {color:#a33e2b;font-size:13px}
.sr-only {position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)}
@media(max-width:550px) {main {padding:22px 18px 40px}.intro {padding:36px 0 28px}.workspace {padding:18px}form {flex-direction:column}form button {padding:14px}.intro h1 {font-size:34px}}
