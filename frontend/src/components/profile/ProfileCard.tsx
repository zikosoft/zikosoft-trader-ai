// §B30 "Profils novice/intermediate/expert" — carte Settings : sélecteur
// 3 voies + tableau des limites du palier actif + avertissement (dialog de
// confirmation, PAS de phrase tapée — contrairement au kill switch, ce
// changement est réversible et sans effet destructeur immédiat, seulement
// une augmentation d'autonomie future) quand l'utilisateur choisit un
// palier plus permissif que l'actuel (`isProfileIncrease`).

import { useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableRow,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";
import ShieldOutlinedIcon from "@mui/icons-material/ShieldOutlined";
import { useLivePolling } from "../../hooks/useLivePolling";
import {
  PROFILE_ORDER,
  fetchUserProfile,
  isProfileIncrease,
  updateUserProfile,
  type ExperienceProfile,
} from "../../api/userProfile";
import { describeError } from "../../api/client";
import { useI18n } from "../../i18n/I18nContext";
import { profileLabel } from "../../i18n/domain";

const POLL_INTERVAL_MS = 15000;

export default function ProfileCard() {
  const { t } = useI18n();
  const { data: profile, refresh } = useLivePolling(fetchUserProfile, POLL_INTERVAL_MS);
  const [pendingSelection, setPendingSelection] = useState<ExperienceProfile | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // État optimiste local, même principe que `AiGovernanceCard.tsx` — le
  // sélecteur répond immédiatement, corrigé par le prochain poll s'il
  // divergeait.
  const [optimisticProfile, setOptimisticProfile] = useState<ExperienceProfile | null>(null);

  useEffect(() => {
    setOptimisticProfile(null);
  }, [profile?.profile]);

  const current = optimisticProfile ?? profile?.profile ?? "novice";

  async function applyProfile(next: ExperienceProfile) {
    setOptimisticProfile(next);
    setBusy(true);
    setError(null);
    try {
      await updateUserProfile(next);
      setPendingSelection(null);
      refresh();
    } catch (err) {
      setOptimisticProfile(null);
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  }

  function handleSelect(next: ExperienceProfile | null) {
    if (!next || next === current || busy) return;
    if (isProfileIncrease(current, next)) {
      setPendingSelection(next);
      return;
    }
    applyProfile(next);
  }

  const limits = profile?.limits;

  return (
    <Paper variant="outlined" sx={{ p: 3, mb: 3 }}>
      <Typography variant="h6" component="h2" sx={{ mb: 1, display: "flex", alignItems: "center", gap: 1 }}>
        <ShieldOutlinedIcon color="primary" />
        {t("profileCard.title")}
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 2 }}>
        {t("profileCard.body")}
      </Typography>

      <ToggleButtonGroup
        value={current}
        exclusive
        onChange={(_e, next) => handleSelect(next)}
        disabled={busy}
        sx={{ mb: 2, flexWrap: "wrap" }}
      >
        {PROFILE_ORDER.map((p) => (
          <ToggleButton key={p} value={p}>
            {profileLabel(t, p)}
          </ToggleButton>
        ))}
      </ToggleButtonGroup>

      {limits && (
        <Table size="small" sx={{ mb: error ? 2 : 0 }}>
          <TableBody>
            <TableRow>
              <TableCell>{t("profileCard.maxActiveStrategies")}</TableCell>
              <TableCell align="right">{limits.max_active_strategies}</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>{t("profileCard.maxSymbols")}</TableCell>
              <TableCell align="right">{limits.max_symbols}</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>{t("profileCard.maxOrderRisk")}</TableCell>
              <TableCell align="right">{limits.order_risk_pct}%</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>{t("profileCard.maxDailyLoss")}</TableCell>
              <TableCell align="right">{limits.daily_loss_pct}%</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>{t("profileCard.orderApproval")}</TableCell>
              <TableCell align="right">
                {t(`profileCard.approval.${limits.approval_mode}`) === `profileCard.approval.${limits.approval_mode}`
                  ? limits.approval_mode
                  : t(`profileCard.approval.${limits.approval_mode}`)}
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
      )}

      {error && (
        <Alert severity="error" sx={{ mt: 2 }}>
          {error}
        </Alert>
      )}

      <Dialog open={pendingSelection !== null} onClose={() => setPendingSelection(null)} maxWidth="xs" fullWidth>
        <DialogTitle>{t("profileCard.confirmTitle")}</DialogTitle>
        <DialogContent>
          <DialogContentText>
            {t("profileCard.confirmBody", {
              profile: pendingSelection ? profileLabel(t, pendingSelection) : "",
            })}
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setPendingSelection(null)} disabled={busy}>
            {t("common.cancel")}
          </Button>
          <Box sx={{ flex: "0 0 auto" }}>
            <Button
              variant="contained"
              color="warning"
              disabled={busy}
              onClick={() => pendingSelection && applyProfile(pendingSelection)}
            >
              {busy ? t("profileCard.working") : t("profileCard.confirm")}
            </Button>
          </Box>
        </DialogActions>
      </Dialog>
    </Paper>
  );
}
