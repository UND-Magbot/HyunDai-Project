import { IconButton } from "../ui/IconButton";
import { AlarmPopover } from "./AlarmPopover";
import type { TopBarProps } from "@/lib/types/shell";

export function TopBar({ dateTime, onToggleNav, navExpanded }: TopBarProps) {
  return (
    <header
      className="top-bar"
      data-nav-collapsed={navExpanded === false ? "true" : "false"}
    >
      <div className="top-bar__left">
        {onToggleNav ? (
          <IconButton
            aria-label="Toggle navigation"
            aria-expanded={navExpanded}
            onClick={onToggleNav}
            className="top-bar__toggle"
            variant="ghost"
          >
            ☰
          </IconButton>
        ) : null}
      </div>
      <h1 className="top-bar__center">현대 글로비스 RCS</h1>
      <div className="top-bar__right">
        <span className="top-bar__datetime">{dateTime}</span>
        <AlarmPopover />
        <div>User Area</div>
      </div>
    </header>
  );
}
