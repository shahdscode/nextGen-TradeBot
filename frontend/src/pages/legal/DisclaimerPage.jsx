import LegalLayout from './LegalLayout'

export default function DisclaimerPage() {
  return (
    <LegalLayout title="Financial Disclaimer" updated="June 2026">
      <p className="text-amber-300 font-medium">
        NextGen TradeBot is decision-support and research software. It is NOT financial,
        investment, or trading advice, and it does not execute real-money trades.
      </p>
      <h2>Not investment advice</h2>
      <p>
        All signals, scores, backtests, paper-trading results, and explanations are provided
        for informational and educational purposes only. They do not constitute a
        recommendation, solicitation, or offer to buy or sell any security or financial
        instrument. We are not a registered broker-dealer, investment adviser, or financial
        planner.
      </p>
      <h2>No guarantee of performance</h2>
      <p>
        Trading involves substantial risk of loss. Past and simulated performance is not
        indicative of future results. Backtests and paper-trading use historical or delayed
        data and assumptions (transaction costs, slippage, fills) that may differ materially
        from live markets. AI models can be wrong and may underperform simple benchmarks.
      </p>
      <h2>Your responsibility</h2>
      <p>
        Any decision you make based on information from this platform is your sole
        responsibility. Consult a licensed financial professional before making investment
        decisions. Only risk capital you can afford to lose.
      </p>
      <h2>No liability</h2>
      <p>
        To the maximum extent permitted by law, the creators of NextGen TradeBot accept no
        liability for any loss or damage arising from the use of this software or reliance on
        its output.
      </p>
    </LegalLayout>
  )
}
