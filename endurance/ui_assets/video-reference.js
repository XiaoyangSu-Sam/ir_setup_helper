export default function ({ parentElement, setTriggerValue }) {
  const file = parentElement.querySelector(".video-file");
  const video = parentElement.querySelector("video");
  const controls = parentElement.querySelector(".player-controls");
  const status = parentElement.querySelector(".player-status");
  const form = parentElement.querySelector("form");
  const captures = [...form.querySelectorAll("[data-mark]")];
  const timeLabel = controls.querySelector("output");

  function ready(loaded) {
    controls.hidden = !loaded;
    for (const button of captures) button.disabled = !loaded;
  }

  file.onchange = () => {
    const old = video.getAttribute("src");
    if (old) URL.revokeObjectURL(old);
    ready(false);
    video.hidden = true;
    status.textContent = "";
    const [selected] = file.files;
    if (!selected) {
      video.removeAttribute("src");
      video.load();
      return;
    }
    status.textContent = "正在读取本机视频…";
    video.src = URL.createObjectURL(selected);
    video.load();
  };
  video.onloadedmetadata = () => {
    video.hidden = false;
    ready(true);
    status.textContent = "";
  };
  video.onerror = () => {
    ready(false);
    video.hidden = true;
    status.textContent = "浏览器无法播放这个文件。可试用 MP4 或 WebM，也可以手填视频时刻。";
  };
  video.ontimeupdate = () => { timeLabel.textContent = video.currentTime.toFixed(3) + " 秒"; };
  for (const button of controls.querySelectorAll("[data-step]")) {
    button.onclick = () => {
      video.pause();
      video.currentTime = Math.min(video.duration, Math.max(0, video.currentTime + Number(button.dataset.step)));
    };
  }
  for (const button of captures) {
    button.onclick = () => {
      video.pause();
      form.elements[button.dataset.mark].value = video.currentTime.toFixed(3);
    };
  }
  form.onsubmit = (event) => {
    event.preventDefault();
    setTriggerValue("marks", Object.fromEntries(new FormData(form)));
  };
  return () => {
    queueMicrotask(() => {
      if (!video.isConnected && video.src.startsWith("blob:")) URL.revokeObjectURL(video.src);
    });
  };
}
