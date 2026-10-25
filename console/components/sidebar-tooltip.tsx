"use client";

import React, { useState, useRef, useEffect, ReactNode } from "react";
import { createPortal } from "react-dom";

interface SidebarTooltipProps {
  label: ReactNode;
  badge?: ReactNode;
  description?: string;
  children: ReactNode;
  enabled?: boolean;
}

export function SidebarTooltip({
  label,
  badge,
  description,
  children,
  enabled = true,
}: SidebarTooltipProps) {
  const [mounted, setMounted] = useState(false);
  const [visible, setVisible] = useState(false);
  const [coords, setCoords] = useState<{ top: number; left: number }>({ top: 0, left: 0 });
  const triggerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setMounted(true);
  }, []);

  const updatePosition = () => {
    if (triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect();
      setCoords({
        top: rect.top + rect.height / 2,
        left: rect.right + 12,
      });
    }
  };

  const handleMouseEnter = () => {
    if (!enabled) return;
    updatePosition();
    setVisible(true);
  };

  const handleMouseLeave = () => {
    setVisible(false);
  };

  // Close tooltip on any parent or window scroll so it doesn't drift
  useEffect(() => {
    if (!visible) return;
    const handleScroll = () => setVisible(false);
    window.addEventListener("scroll", handleScroll, { passive: true, capture: true });
    return () => {
      window.removeEventListener("scroll", handleScroll, { capture: true });
    };
  }, [visible]);

  return (
    <div
      ref={triggerRef}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      className="relative flex items-center justify-center w-full"
    >
      {children}
      {mounted &&
        visible &&
        enabled &&
        createPortal(
          <div
            style={{
              position: "fixed",
              top: `${coords.top}px`,
              left: `${coords.left}px`,
              transform: "translateY(-50%)",
              zIndex: 99999,
              pointerEvents: "none",
            }}
            className="px-3 py-2 rounded-xl bg-[#151822] border border-white/15 text-[#f4f0ea] text-[12px] font-mono shadow-[0_16px_40px_rgba(0,0,0,0.65)] whitespace-nowrap flex items-center gap-2 animate-in fade-in zoom-in-95 duration-100"
          >
            {/* Left caret pointer pointing directly at the icon */}
            <div
              className="absolute -left-[5px] top-1/2 -translate-y-1/2 w-2.5 h-2.5 rotate-45 bg-[#151822] border-l border-b border-white/15"
              aria-hidden
            />
            <div className="flex flex-col relative z-10">
              <div className="flex items-center gap-2">
                <span className="text-[#f4f0ea] font-semibold tracking-tight">{label}</span>
                {badge}
              </div>
              {description ? (
                <span className="text-[10px] text-[#9fa2ab] font-sans leading-tight mt-0.5">
                  {description}
                </span>
              ) : null}
            </div>
          </div>,
          document.body
        )}
    </div>
  );
}
