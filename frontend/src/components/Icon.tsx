// Иконки — исходные SVG из страницы «Компоненты / Иконки» Figma (20×20).
// Рисуются через CSS-маску, поэтому берут цвет текста (currentColor), как в макете: серые / синие / белые.
import bell from "../assets/icons/bell.svg";
import chart from "../assets/icons/chart.svg";
import chat from "../assets/icons/chat.svg";
import check from "../assets/icons/check.svg";
import chevronDown from "../assets/icons/chevron-down.svg";
import chevronRight from "../assets/icons/chevron-right.svg";
import document from "../assets/icons/document.svg";
import download from "../assets/icons/download.svg";
import filter from "../assets/icons/filter.svg";
import folder from "../assets/icons/folder.svg";
import link from "../assets/icons/link.svg";
import lock from "../assets/icons/lock.svg";
import panelHide from "../assets/icons/panel-hide.svg";
import panelShow from "../assets/icons/panel-show.svg";
import pause from "../assets/icons/pause.svg";
import pencil from "../assets/icons/pencil.svg";
import pin from "../assets/icons/pin.svg";
import play from "../assets/icons/play.svg";
import plus from "../assets/icons/plus.svg";
import question from "../assets/icons/question.svg";
import quote from "../assets/icons/quote.svg";
import search from "../assets/icons/search.svg";
import settings from "../assets/icons/settings.svg";
import sparkles from "../assets/icons/sparkles.svg";
import spinner from "../assets/icons/spinner.svg";
import upload from "../assets/icons/upload.svg";
import user from "../assets/icons/user.svg";
import warning from "../assets/icons/warning.svg";

const ICONS = {
  bell, chart, chat, check, chevronDown, chevronRight, document, download, filter, folder, link, lock,
  panelHide, panelShow, pause, pencil, pin, play, plus, question, quote, search, settings, sparkles, spinner,
  upload, user, warning,
} as const;

export type IconName = keyof typeof ICONS;

export function Icon({ name, size = 20, className }: { name: IconName; size?: number; className?: string }) {
  const url = `url("${ICONS[name]}")`;
  return (
    <span
      aria-hidden
      className={`icon${className ? ` ${className}` : ""}`}
      style={{ width: size, height: size, maskImage: url, WebkitMaskImage: url }}
    />
  );
}
