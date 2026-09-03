/** A validated long-option contract selected by the shared backend policy. */
export type OptionInstrument = {
  asset_class: "option";
  underlying_symbol: string;
  symbol: string;
  option_type: "call" | "put";
  expiration_date: string;
  strike_price: number;
  bid_price: number;
  ask_price: number;
  limit_price: number;
  contract_size: number;
  quantity: number;
  estimated_premium: number;
  max_loss: number;
  spread_pct: number;
  open_interest: number | null;
  delta: number | null;
};
