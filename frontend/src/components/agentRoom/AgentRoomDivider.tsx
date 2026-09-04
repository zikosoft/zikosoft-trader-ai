import { useCallback, useEffect, useRef } from "react";
import { Box } from "@mui/material";
import { useI18n } from "../../i18n/I18nContext";

// §B28 checklist "mode Docked... divider redimensionnable" — glisser
// horizontalement change la largeur du panneau Agent Room par rapport au
// contenu principal (défaut 65/35, D010/D011). Les bornes viennent du shell
// afin de préserver une largeur physique minimale au Room et à la page.

type Props = {
  // Largeur actuelle du panneau Agent Room, en % de la largeur du
  // conteneur flex parent.
  panelPercent: number;
  minPercent: number;
  maxPercent: number;
  onChange: (percent: number) => void;
  containerRef: React.RefObject<HTMLDivElement | null>;
};

export default function AgentRoomDivider({ panelPercent, minPercent, maxPercent, onChange, containerRef }: Props) {
  const { t } = useI18n();
  const draggingRef = useRef(false);

  const handlePointerMove = useCallback(
    (event: PointerEvent) => {
      if (!draggingRef.current || !containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      if (rect.width === 0) return;
      // Le panneau est à DROITE du diviseur — sa largeur est la distance
      // entre le pointeur et le bord droit du conteneur.
      const percentFromRight = ((rect.right - event.clientX) / rect.width) * 100;
      const clamped = Math.min(maxPercent, Math.max(minPercent, percentFromRight));
      onChange(clamped);
    },
    [containerRef, maxPercent, minPercent, onChange],
  );

  const handlePointerUp = useCallback(() => {
    draggingRef.current = false;
  }, []);

  useEffect(() => {
    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", handlePointerUp);
    return () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerUp);
    };
  }, [handlePointerMove, handlePointerUp]);

  return (
    <Box
      role="separator"
      aria-orientation="vertical"
      aria-label={t("agentRoom.resize")}
      aria-valuenow={Math.round(panelPercent)}
      aria-valuemin={Math.round(minPercent)}
      aria-valuemax={Math.round(maxPercent)}
      tabIndex={0}
      onPointerDown={() => {
        draggingRef.current = true;
      }}
      onKeyDown={(event) => {
        if (event.key === "ArrowLeft") onChange(Math.min(maxPercent, panelPercent + 2));
        if (event.key === "ArrowRight") onChange(Math.max(minPercent, panelPercent - 2));
      }}
      sx={{
        width: 6,
        flexShrink: 0,
        cursor: "col-resize",
        bgcolor: "divider",
        "&:hover": { bgcolor: "primary.main" },
      }}
    />
  );
}
