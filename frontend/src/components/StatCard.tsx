import { Paper, Typography } from "@mui/material";

// §B26 — petite carte de statistique réutilisable (Portfolio value, Cash,
// Buying power, Daily/Total P&L…) : même style pour tous les chiffres
// "à un coup d'œil" du tableau de bord principal.

type Props = {
  label: string;
  value: string;
  color?: "success.main" | "error.main" | "text.primary";
};

export default function StatCard({ label, value, color = "text.primary" }: Props) {
  return (
    <Paper variant="outlined" sx={{ p: 2, height: "100%" }}>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
        {label}
      </Typography>
      <Typography variant="h5" component="p" sx={{ color }}>
        {value}
      </Typography>
    </Paper>
  );
}
