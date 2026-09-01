import { Box, Chip, List, ListItem, ListItemText, Paper, Skeleton, Typography } from "@mui/material";
import { Link as RouterLink } from "react-router-dom";
import { useLivePolling } from "../../hooks/useLivePolling";
import { fetchStrategyInstances } from "../../api/strategies";
import { fetchRecentOrders } from "../../api/orders";
import { fetchRecentAgentDecisions, fetchRecentRiskDecisions } from "../../api/agentActivity";

// §B26 "Stratégies actives", "Ordres récents", "Résumé Agent Room",
// "Risque" — quatre petits widgets de synthèse, chacun propriétaire de son
// propre poll (§D058/D060 — pas de store partagé), à partir de données
// déjà réellement écrites par des briques précédentes (B12/B17/B13-14/B15).
// Portée volontairement en lecture seule, mêmes dernières N lignes — voir
// les routers backend correspondants pour la justification complète.

function relativeTime(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const minutes = Math.round(diffMs / 60000);
  if (minutes < 1) return "à l'instant";
  if (minutes < 60) return `il y a ${minutes} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `il y a ${hours} h`;
  return `il y a ${Math.round(hours / 24)} j`;
}

function WidgetCard({ title, children, action }: { title: string; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <Paper variant="outlined" sx={{ p: 2, height: "100%" }}>
      <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center", mb: 1 }}>
        <Typography variant="h6" component="h2">
          {title}
        </Typography>
        {action}
      </Box>
      {children}
    </Paper>
  );
}

export function StrategiesCard() {
  const { data, loading } = useLivePolling(fetchStrategyInstances, 5000);

  if (loading && !data) return <Skeleton variant="rectangular" height={160} sx={{ borderRadius: 1 }} />;

  const instances = data ?? [];
  const active = instances.filter((i) => i.status === "ACTIVE");

  return (
    <WidgetCard title="Stratégies actives">
      <Typography variant="h4" component="p" sx={{ mb: 1 }}>
        {active.length}
      </Typography>
      {active.length === 0 ? (
        <Typography color="text.secondary">Aucune stratégie active pour le moment.</Typography>
      ) : (
        <List dense disablePadding>
          {active.slice(0, 5).map((i) => (
            <ListItem key={i.id} disableGutters>
              <ListItemText primary={i.name} secondary={i.symbols.join(", ")} />
            </ListItem>
          ))}
        </List>
      )}
    </WidgetCard>
  );
}

export function OrdersCard() {
  const { data, loading } = useLivePolling(() => fetchRecentOrders(5), 5000);

  if (loading && !data) return <Skeleton variant="rectangular" height={160} sx={{ borderRadius: 1 }} />;

  const orders = data?.orders ?? [];

  return (
    <WidgetCard title="Ordres récents">
      {orders.length === 0 ? (
        <Typography color="text.secondary">Aucun ordre pour le moment.</Typography>
      ) : (
        <List dense disablePadding>
          {orders.map((o) => (
            <ListItem key={o.id} disableGutters>
              <ListItemText
                primary={`${o.side === "buy" ? "Achat" : "Vente"} ${o.symbol}${o.quantity ? ` × ${o.quantity}` : ""}`}
                secondary={relativeTime(o.created_at)}
              />
              <Chip label={o.status} size="small" variant="outlined" />
            </ListItem>
          ))}
        </List>
      )}
    </WidgetCard>
  );
}

export function AgentActivityCard() {
  const { data, loading } = useLivePolling(() => fetchRecentAgentDecisions(5), 5000);

  if (loading && !data) return <Skeleton variant="rectangular" height={160} sx={{ borderRadius: 1 }} />;

  const decisions = data?.decisions ?? [];

  return (
    <WidgetCard
      title="Résumé Agent Room"
      action={
        <Chip component={RouterLink} to="/agent-room" clickable label="Voir tout" size="small" variant="outlined" />
      }
    >
      {decisions.length === 0 ? (
        <Typography color="text.secondary">Aucune activité d'agent pour le moment.</Typography>
      ) : (
        <List dense disablePadding>
          {decisions.map((d) => (
            <ListItem key={d.id} disableGutters>
              <ListItemText primary={`${d.agent_type} — ${d.outcome}`} secondary={relativeTime(d.created_at)} />
            </ListItem>
          ))}
        </List>
      )}
    </WidgetCard>
  );
}

const RISK_OUTCOME_COLOR: Record<string, "success" | "warning" | "error" | "default"> = {
  APPROVED: "success",
  ADJUSTED: "warning",
  REQUIRES_APPROVAL: "warning",
  REJECTED: "error",
};

export function RiskCard() {
  const { data, loading } = useLivePolling(() => fetchRecentRiskDecisions(5), 5000);

  if (loading && !data) return <Skeleton variant="rectangular" height={160} sx={{ borderRadius: 1 }} />;

  const decisions = data?.decisions ?? [];

  return (
    <WidgetCard title="Risque">
      {decisions.length === 0 ? (
        <Typography color="text.secondary">Aucune décision de risque pour le moment.</Typography>
      ) : (
        <List dense disablePadding>
          {decisions.map((d) => (
            <ListItem key={d.id} disableGutters>
              <ListItemText primary={relativeTime(d.created_at)} />
              <Chip label={d.outcome} size="small" color={RISK_OUTCOME_COLOR[d.outcome] ?? "default"} />
            </ListItem>
          ))}
        </List>
      )}
    </WidgetCard>
  );
}
