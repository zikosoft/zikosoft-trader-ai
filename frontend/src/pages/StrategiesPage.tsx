import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  Collapse,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  Grid,
  IconButton,
  MenuItem,
  Paper,
  Skeleton,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Tooltip,
  Typography,
} from "@mui/material";
import DeleteIcon from "@mui/icons-material/Delete";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import EditIcon from "@mui/icons-material/Edit";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import PauseIcon from "@mui/icons-material/Pause";
import StopIcon from "@mui/icons-material/Stop";
import { useLivePolling } from "../hooks/useLivePolling";
import { ApiError, describeError } from "../api/client";
import SymbolAutocomplete from "../components/assets/SymbolAutocomplete";
import {
  activateStrategyInstance,
  cloneStrategyInstance,
  createStrategyInstance,
  deleteStrategyInstance,
  fetchStrategyDefinitions,
  fetchStrategyInstances,
  pauseStrategyInstance,
  stopStrategyInstance,
  updateStrategyInstance,
  type StrategyDefinition,
  type StrategyInstance,
  type StrategyInstanceStatus,
  type UiFieldSchema,
} from "../api/strategies";
import { fetchUserProfile, type UserProfile } from "../api/userProfile";
import { useI18n } from "../i18n/I18nContext";
import { localizeValue, profileLabel, strategyDescription, strategyEnumLabel, strategyLabel, strategyParameterLabel } from "../i18n/domain";

// §écran dédié Strategies (28/08 — fermeture des liens de menu B12/B25/B26,
// voir AVANCEMENT.md) — remplace le `PlaceholderPage` "Backend prêt depuis
// B11-B12 — UI à venir". Le CRUD complet (`backend/app/routers/
// strategy_instances.py`, 8 routes) et le registre auto-descriptif
// (`parameter_schema`/`ui_schema`/`defaults_by_profile` par définition,
// B11) existaient déjà et étaient déjà testés — cet écran assemble un
// formulaire de création générique piloté par ces schémas (aucune des 3
// stratégies n'a de formulaire codé en dur) plus un tableau de gestion des
// instances (activer/mettre en pause/arrêter/cloner/supprimer), sans
// aucune nouvelle route backend.

const STATUS_COLOR: Record<StrategyInstanceStatus, "success" | "warning" | "default" | "error"> = {
  DRAFT: "default",
  READY: "default",
  ACTIVE: "success",
  PAUSED: "warning",
  STOPPED: "default",
  ERROR: "error",
};

function sortedFields(uiSchema: Record<string, UiFieldSchema>): [string, UiFieldSchema][] {
  return Object.entries(uiSchema).sort((a, b) => a[1].order - b[1].order);
}

// §B30 "Champs avancés masqués selon profil" — aucune des 3 définitions de
// stratégie (`strategies/*/definition.py`) ne marque ses champs
// `advanced`/`basic` côté backend (le `ui_schema` ne porte que
// `widget`/`label`/`order`, voir `api/strategies.ts`) : cette heuristique
// est donc VOLONTAIREMENT frontend-only, sur le nom du paramètre plutôt que
// sur un champ de schéma qui n'existe pas. `period`/`threshold`/
// `frequency` couvrent les 3 paramètres de réglage technique des
// stratégies existantes (`short_period`/`long_period`/`rsi_period`,
// `oversold_threshold`/`overbought_threshold`, `analysis_frequency`) —
// jamais un champ d'exposition au risque. §checklist "Risques/pertes
// toujours visibles" : `stop_loss_pct`/`take_profit_pct` (et tout champ
// exprimant risque/capital — `risk_posture`, `min_confidence`,
// `max_notional_usd`, `require_human_approval`) ne correspondent à aucun de
// ces 3 motifs et restent donc TOUJOURS dans la section de base, jamais
// masqués, quel que soit le profil.
function isAdvancedField(key: string): boolean {
  return /period|threshold|frequency/i.test(key);
}

function renderField(
  key: string,
  field: UiFieldSchema,
  definition: StrategyDefinition,
  values: Record<string, unknown>,
  setField: (key: string, value: unknown) => void,
  t: ReturnType<typeof useI18n>["t"],
) {
  const propSchema = definition.parameter_schema.properties[key];
  const value = values[key];

  if (field.widget === "select") {
    return (
      <Grid key={key} size={{ xs: 12, sm: 6 }}>
        <TextField select fullWidth label={strategyParameterLabel(t, key, field.label)} value={(value as string) ?? ""} onChange={(e) => setField(key, e.target.value)}>
          {(propSchema?.enum ?? []).map((opt) => (
            <MenuItem key={opt} value={opt}>
              {strategyEnumLabel(t, opt)}
            </MenuItem>
          ))}
        </TextField>
      </Grid>
    );
  }

  if (field.widget === "checkbox") {
    return (
      <Grid key={key} size={{ xs: 12, sm: 6 }}>
        <FormControlLabel
          control={<Checkbox checked={Boolean(value)} onChange={(e) => setField(key, e.target.checked)} />}
          label={strategyParameterLabel(t, key, field.label)}
        />
      </Grid>
    );
  }

  // widget "number" — couvre integer/number côté schéma.
  return (
    <Grid key={key} size={{ xs: 12, sm: 6 }}>
      <TextField
        type="number"
        fullWidth
        label={strategyParameterLabel(t, key, field.label)}
        value={value === undefined || value === null ? "" : String(value)}
        slotProps={{
          htmlInput: {
            min: propSchema?.minimum ?? propSchema?.exclusiveMinimum,
            max: propSchema?.maximum,
            step: propSchema?.type === "integer" ? 1 : "any",
          },
        }}
        onChange={(e) => {
          const raw = e.target.value;
          if (raw === "") {
            setField(key, undefined);
            return;
          }
          setField(key, propSchema?.type === "integer" ? parseInt(raw, 10) : parseFloat(raw));
        }}
      />
    </Grid>
  );
}

// Formulaire de paramètres générique — un seul composant pour les 3
// stratégies prédéfinies (et toute future stratégie qui respecterait la
// même convention `parameter_schema`/`ui_schema`), piloté entièrement par
// le schéma renvoyé par le backend plutôt que par 3 formulaires codés en
// dur par type de stratégie. §B30 — les champs "avancés" (voir
// `isAdvancedField`) vont dans une section repliable, ouverte par défaut
// selon le profil d'expérience de l'utilisateur (`defaultAdvancedOpen`).
function ParameterForm({
  definition,
  values,
  onChange,
  defaultAdvancedOpen,
}: {
  definition: StrategyDefinition;
  values: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
  defaultAdvancedOpen: boolean;
}) {
  const { t } = useI18n();
  const [advancedOpen, setAdvancedOpen] = useState(defaultAdvancedOpen);

  useEffect(() => {
    setAdvancedOpen(defaultAdvancedOpen);
  }, [defaultAdvancedOpen, definition.type_code]);

  function setField(key: string, value: unknown) {
    onChange({ ...values, [key]: value });
  }

  const fields = sortedFields(definition.ui_schema);
  const basicFields = fields.filter(([key]) => !isAdvancedField(key));
  const advancedFields = fields.filter(([key]) => isAdvancedField(key));

  return (
    <Box>
      <Grid container spacing={2}>
        {basicFields.map(([key, field]) => renderField(key, field, definition, values, setField, t))}
      </Grid>

      {advancedFields.length > 0 && (
        <Box sx={{ mt: 2 }}>
          <Button
            size="small"
            onClick={() => setAdvancedOpen((v) => !v)}
            startIcon={advancedOpen ? <ExpandLessIcon /> : <ExpandMoreIcon />}
            sx={{ mb: 1 }}
          >
            {t("strategy.advancedParameters")}
          </Button>
          <Collapse in={advancedOpen}>
            <Grid container spacing={2}>
              {advancedFields.map(([key, field]) => renderField(key, field, definition, values, setField, t))}
            </Grid>
          </Collapse>
        </Box>
      )}
    </Box>
  );
}

// §B30 — mappe le profil d'expérience utilisateur (novice/intermediate/
// expert) sur les 2 paliers de paramètres par défaut de B12
// (`defaults_by_profile`, "beginner"/"advanced") plutôt que de réécrire ce
// mécanisme existant en 3 paliers : novice/intermediate restent prudents
// ("beginner"), seul expert bascule sur "advanced" (voir décision au
// registre AVANCEMENT.md — B30).
function strategyProfileFor(experienceProfile: UserProfile["profile"] | undefined): "beginner" | "advanced" {
  return experienceProfile === "expert" ? "advanced" : "beginner";
}

function CreateStrategyDialog({
  open,
  definitions,
  userProfile,
  onClose,
  onCreated,
}: {
  open: boolean;
  definitions: StrategyDefinition[];
  userProfile: UserProfile | null;
  onClose: () => void;
  onCreated: () => void;
}) {
  const { t } = useI18n();
  const [typeCode, setTypeCode] = useState("");
  const [name, setName] = useState("");
  const [symbols, setSymbols] = useState<string[]>([]);
  const [profile, setProfile] = useState<"beginner" | "advanced">("beginner");
  const [parameters, setParameters] = useState<Record<string, unknown>>({});
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<string[]>([]);

  const definition = useMemo(() => definitions.find((d) => d.type_code === typeCode) ?? null, [definitions, typeCode]);
  // §B30 "Champs avancés masqués selon profil" — repliés par défaut pour
  // `novice`, dépliés pour `intermediate`/`expert` (seul `novice` a besoin
  // d'un formulaire simplifié en priorité).
  const defaultAdvancedOpen = userProfile ? userProfile.profile !== "novice" : false;

  useEffect(() => {
    if (!open) return;
    // §réinitialisation à chaque ouverture — évite de réafficher les
    // paramètres/erreurs d'une création précédente.
    setTypeCode(definitions[0]?.type_code ?? "");
    setName("");
    setSymbols([]);
    setProfile(strategyProfileFor(userProfile?.profile));
    setError(null);
    setFieldErrors([]);
  }, [open, definitions, userProfile]);

  useEffect(() => {
    if (!definition) return;
    setParameters(definition.defaults_by_profile[profile] ?? {});
  }, [definition, profile]);

  async function handleSubmit() {
    if (!definition || !name.trim() || symbols.length === 0) return;
    setSubmitting(true);
    setError(null);
    setFieldErrors([]);
    try {
      await createStrategyInstance({
        type_code: definition.type_code,
        name: name.trim(),
        symbols,
        parameters,
      });
      onCreated();
      onClose();
    } catch (err) {
      if (err instanceof ApiError && err.code === "VALIDATION_ERROR" && Array.isArray(err.details?.errors)) {
        setFieldErrors(err.details.errors as string[]);
      } else {
        setError(describeError(err));
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>{t("strategy.createTitle")}</DialogTitle>
      <DialogContent dividers>
        <Box sx={{ display: "flex", flexDirection: "column", gap: 2, pt: 0.5 }}>
          <TextField
            select
            fullWidth
            label={t("strategy.type")}
            value={typeCode}
            onChange={(e) => setTypeCode(e.target.value)}
          >
            {definitions.map((d) => (
              <MenuItem key={d.type_code} value={d.type_code}>
                {strategyLabel(t, d.type_code, d.name)}
              </MenuItem>
            ))}
          </TextField>

          {definition && (
            <Typography variant="body2" color="text.secondary">
              {strategyDescription(t, definition.type_code, definition.description)}
              {definition.required_capabilities.includes("ai") && (
                <>
                  {" "}
                  <Chip label={t("strategy.aiRequired")} size="small" color="info" variant="outlined" sx={{ ml: 0.5 }} />
                </>
              )}
            </Typography>
          )}

          <TextField fullWidth label={t("common.name")} value={name} onChange={(e) => setName(e.target.value)} />
          <SymbolAutocomplete value={symbols} onChange={setSymbols} maxSymbols={userProfile?.limits.max_symbols} />

          {definition && (
            <>
              <ToggleButtonGroup
                exclusive
                size="small"
                value={profile}
                onChange={(_e, v) => v && setProfile(v)}
                sx={{ alignSelf: "flex-start" }}
              >
                <ToggleButton value="beginner">{profileLabel(t, "novice")}</ToggleButton>
                <ToggleButton value="advanced">{profileLabel(t, "expert")}</ToggleButton>
              </ToggleButtonGroup>

              <ParameterForm
                definition={definition}
                values={parameters}
                onChange={setParameters}
                defaultAdvancedOpen={defaultAdvancedOpen}
              />
            </>
          )}

          {fieldErrors.length > 0 && (
            <Alert severity="error">
              {fieldErrors.map((e) => (
                <div key={e}>{e}</div>
              ))}
            </Alert>
          )}
          {error && <Alert severity="error">{error}</Alert>}
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t("common.cancel")}</Button>
        <Button
          variant="contained"
          disabled={submitting || !definition || !name.trim() || symbols.length === 0}
          onClick={handleSubmit}
        >
          {submitting ? t("strategy.creating") : t("common.create")}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

// Editing intentionally reuses the definition-driven parameter form from
// creation. A strategy must be paused or stopped first: changing its market
// timeframe while an agent is processing it would make a Paper decision
// ambiguous. The existing backend PATCH endpoint already enforces that same
// lifecycle rule; this dialog exposes it in the UI.
function EditStrategyDialog({
  target,
  definitions,
  userProfile,
  onClose,
  onUpdated,
}: {
  target: StrategyInstance | null;
  definitions: StrategyDefinition[];
  userProfile: UserProfile | null;
  onClose: () => void;
  onUpdated: () => void;
}) {
  const { t } = useI18n();
  const [name, setName] = useState("");
  const [symbols, setSymbols] = useState<string[]>([]);
  const [parameters, setParameters] = useState<Record<string, unknown>>({});
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<string[]>([]);
  const definition = useMemo(
    () => definitions.find((item) => item.type_code === target?.type_code) ?? null,
    [definitions, target?.type_code],
  );

  useEffect(() => {
    if (!target) return;
    setName(target.name);
    setSymbols(target.symbols);
    setParameters(target.parameters ?? {});
    setError(null);
    setFieldErrors([]);
  }, [target]);

  async function handleSubmit() {
    if (!target || !definition || !name.trim() || symbols.length === 0) return;
    setSubmitting(true);
    setError(null);
    setFieldErrors([]);
    try {
      await updateStrategyInstance(target.id, {
        name: name.trim(),
        symbols,
        parameters,
        risk_configuration: target.risk_configuration ?? {},
      });
      onUpdated();
      onClose();
    } catch (err) {
      if (err instanceof ApiError && err.code === "VALIDATION_ERROR" && Array.isArray(err.details?.errors)) {
        setFieldErrors(err.details.errors as string[]);
      } else {
        setError(describeError(err));
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={target !== null} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>{t("strategy.editTitle")}</DialogTitle>
      <DialogContent dividers>
        <Box sx={{ display: "flex", flexDirection: "column", gap: 2, pt: 0.5 }}>
          {definition && (
            <Typography variant="body2" color="text.secondary">
              {strategyDescription(t, definition.type_code, definition.description)}
            </Typography>
          )}
          <TextField fullWidth label={t("common.name")} value={name} onChange={(event) => setName(event.target.value)} />
          <SymbolAutocomplete value={symbols} onChange={setSymbols} maxSymbols={userProfile?.limits.max_symbols} />
          {definition && (
            <ParameterForm
              definition={definition}
              values={parameters}
              onChange={setParameters}
              defaultAdvancedOpen={userProfile?.profile !== "novice"}
            />
          )}
          {fieldErrors.length > 0 && (
            <Alert severity="error">
              {fieldErrors.map((item) => (
                <div key={item}>{item}</div>
              ))}
            </Alert>
          )}
          {error && <Alert severity="error">{error}</Alert>}
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t("common.cancel")}</Button>
        <Button
          variant="contained"
          disabled={submitting || !definition || !name.trim() || symbols.length === 0}
          onClick={handleSubmit}
        >
          {t("common.save")}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

export default function StrategiesPage() {
  const { t } = useI18n();
  const { data: instances, error, loading, refresh } = useLivePolling(fetchStrategyInstances, 5000);
  const [definitions, setDefinitions] = useState<StrategyDefinition[] | null>(null);
  const [userProfile, setUserProfile] = useState<UserProfile | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<StrategyInstance | null>(null);
  const [editTarget, setEditTarget] = useState<StrategyInstance | null>(null);

  useEffect(() => {
    fetchStrategyDefinitions()
      .then(setDefinitions)
      .catch(() => setDefinitions([]));
    // §B30 — profil utilisateur chargé une fois ici plutôt que dans le
    // dialog de création (évite un refetch à chaque ouverture) ; `null` en
    // cas d'échec réseau reste géré partout en aval (`userProfile?.…`).
    fetchUserProfile()
      .then(setUserProfile)
      .catch(() => setUserProfile(null));
  }, []);

  async function runAction(id: string, action: (id: string) => Promise<unknown>) {
    setPendingId(id);
    setActionError(null);
    try {
      await action(id);
      refresh();
    } catch (err) {
      setActionError(describeError(err));
    } finally {
      setPendingId(null);
    }
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    setPendingId(deleteTarget.id);
    setActionError(null);
    try {
      await deleteStrategyInstance(deleteTarget.id);
      setDeleteTarget(null);
      refresh();
    } catch (err) {
      setActionError(describeError(err));
    } finally {
      setPendingId(null);
    }
  }

  if (loading && !instances && !error) {
    return (
      <Box>
        <Skeleton variant="text" width={220} height={48} sx={{ mb: 2 }} />
        <Skeleton variant="rectangular" height={300} sx={{ borderRadius: 1 }} />
      </Box>
    );
  }

  if (!instances && error instanceof ApiError && error.code === "VALIDATION_ERROR") {
    return (
      <Box>
        <Typography variant="h4" component="h1" sx={{ mb: 2 }}>
          {t("navigation.strategies")}
        </Typography>
        <Alert severity="info">{t("strategy.noContext")}</Alert>
      </Box>
    );
  }

  if (!instances && error) {
    return (
      <Box>
        <Typography variant="h4" component="h1" sx={{ mb: 2 }}>
          {t("navigation.strategies")}
        </Typography>
        <Alert severity="error">{describeError(error)}</Alert>
      </Box>
    );
  }

  const list = instances ?? [];

  return (
    <Box>
      <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center", mb: 2 }}>
        <Typography variant="h4" component="h1">
          {t("navigation.strategies")}
        </Typography>
        <Button variant="contained" disabled={!definitions || definitions.length === 0} onClick={() => setCreateOpen(true)}>
          {t("strategy.create")}
        </Button>
      </Box>

      {actionError && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setActionError(null)}>
          {actionError}
        </Alert>
      )}
      {error !== null && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          {describeError(error)} — {t("common.lastKnownData")}
        </Alert>
      )}

      <Paper variant="outlined" sx={{ p: 2 }}>
        {list.length === 0 ? (
          <Typography color="text.secondary">
            {t("strategy.empty")}
          </Typography>
        ) : (
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>{t("common.name")}</TableCell>
                <TableCell>{t("strategy.type")}</TableCell>
                <TableCell>{t("strategy.symbols")}</TableCell>
                <TableCell>{t("common.status")}</TableCell>
                <TableCell>{t("strategy.latestSignal")}</TableCell>
                <TableCell align="right">{t("common.actions")}</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {list.map((instance) => {
                const busy = pendingId === instance.id;
                // STOPPED means the previous run ended; the configured
                // strategy remains reusable and can be started again.
                const canActivate = instance.status === "READY" || instance.status === "PAUSED" || instance.status === "STOPPED";
                const canPause = instance.status === "ACTIVE";
                const canStop =
                  instance.status === "ACTIVE" ||
                  instance.status === "PAUSED" ||
                  instance.status === "READY" ||
                  instance.status === "DRAFT";
                const canDelete = instance.status !== "ACTIVE";
                const canEdit = instance.status !== "ACTIVE";

                return (
                  <TableRow key={instance.id}>
                    <TableCell>{instance.name}</TableCell>
                    <TableCell>{strategyLabel(t, instance.type_code, instance.type_code)}</TableCell>
                    <TableCell>{instance.symbols.join(", ")}</TableCell>
                    <TableCell>
                      <Chip label={localizeValue(t, `status.${instance.status}`, instance.status)} size="small" color={STATUS_COLOR[instance.status]} variant="outlined" />
                    </TableCell>
                    <TableCell>{instance.latest_signal ?? "—"}</TableCell>
                    <TableCell align="right">
                      <Tooltip title={t("strategy.activate")}>
                        <span>
                          <IconButton
                            size="small"
                            disabled={!canActivate || busy}
                            onClick={() => runAction(instance.id, activateStrategyInstance)}
                          >
                            <PlayArrowIcon fontSize="small" />
                          </IconButton>
                        </span>
                      </Tooltip>
                      <Tooltip title={t("strategy.pause")}>
                        <span>
                          <IconButton
                            size="small"
                            disabled={!canPause || busy}
                            onClick={() => runAction(instance.id, pauseStrategyInstance)}
                          >
                            <PauseIcon fontSize="small" />
                          </IconButton>
                        </span>
                      </Tooltip>
                      <Tooltip title={t("strategy.stop")}>
                        <span>
                          <IconButton
                            size="small"
                            disabled={!canStop || busy}
                            onClick={() => runAction(instance.id, stopStrategyInstance)}
                          >
                            <StopIcon fontSize="small" />
                          </IconButton>
                        </span>
                      </Tooltip>
                      <Tooltip title={canEdit ? t("strategy.edit") : t("strategy.editUnavailable")}>
                        <span>
                          <IconButton
                            size="small"
                            disabled={!canEdit || busy}
                            onClick={() => setEditTarget(instance)}
                          >
                            <EditIcon fontSize="small" />
                          </IconButton>
                        </span>
                      </Tooltip>
                      <Tooltip title={t("strategy.clone")}>
                        <span>
                          <IconButton
                            size="small"
                            disabled={busy}
                            onClick={() => runAction(instance.id, (id) => cloneStrategyInstance(id))}
                          >
                            <ContentCopyIcon fontSize="small" />
                          </IconButton>
                        </span>
                      </Tooltip>
                      <Tooltip title={t("common.delete")}>
                        <span>
                          <IconButton
                            size="small"
                            disabled={!canDelete || busy}
                            onClick={() => setDeleteTarget(instance)}
                          >
                            <DeleteIcon fontSize="small" />
                          </IconButton>
                        </span>
                      </Tooltip>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </Paper>

      <CreateStrategyDialog
        open={createOpen}
        definitions={definitions ?? []}
        userProfile={userProfile}
        onClose={() => setCreateOpen(false)}
        onCreated={() => refresh()}
      />

      <EditStrategyDialog
        target={editTarget}
        definitions={definitions ?? []}
        userProfile={userProfile}
        onClose={() => setEditTarget(null)}
        onUpdated={() => refresh()}
      />

      <Dialog open={deleteTarget !== null} onClose={() => setDeleteTarget(null)}>
        <DialogTitle>{t("strategy.deleteTitle", { name: deleteTarget?.name ?? "" })}</DialogTitle>
        <DialogContent>
          <Typography color="text.secondary">
            {t("strategy.deleteBody")}
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteTarget(null)}>{t("common.cancel")}</Button>
          <Button color="error" variant="contained" disabled={pendingId === deleteTarget?.id} onClick={handleDelete}>
            {t("common.delete")}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
