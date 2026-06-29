import LegalLayout from './LegalLayout'

export default function TermsPage() {
  return (
    <LegalLayout title="Terms of Service" updated="June 2026">
      <p>
        By creating an account or using NextGen TradeBot ("the Service"), you agree to these
        Terms. If you do not agree, do not use the Service.
      </p>
      <h2>1. The Service</h2>
      <p>
        NextGen TradeBot is an AI-powered quantitative research and paper-trading platform. It
        provides trading signals, backtests, analytics, and explanations for educational and
        informational purposes. The Service does not execute real-money trades and is not
        financial advice (see our <a href="/disclaimer" className="text-teal-400">Financial Disclaimer</a>).
      </p>
      <h2>2. Accounts</h2>
      <p>
        You are responsible for safeguarding your credentials and for all activity under your
        account. Provide accurate information and keep it up to date. We may suspend accounts
        that abuse the Service or violate these Terms.
      </p>
      <h2>3. Acceptable use</h2>
      <p>
        You agree not to misuse the Service, including attempting to disrupt it, access other
        users' data, scrape at scale, or use it for unlawful purposes.
      </p>
      <h2>4. Third-party services</h2>
      <p>
        The Service integrates third-party data and brokerage providers (e.g. market data and
        Alpaca paper trading). Your use of those services is subject to their own terms, and we
        are not responsible for their availability or accuracy.
      </p>
      <h2>5. No warranty</h2>
      <p>
        The Service is provided "as is" without warranties of any kind. We do not guarantee
        accuracy, availability, or any financial outcome.
      </p>
      <h2>6. Limitation of liability</h2>
      <p>
        To the maximum extent permitted by law, we are not liable for any indirect, incidental,
        or consequential damages, or for any trading losses arising from use of the Service.
      </p>
      <h2>7. Changes</h2>
      <p>
        We may update these Terms. Continued use after changes constitutes acceptance.
      </p>
    </LegalLayout>
  )
}
