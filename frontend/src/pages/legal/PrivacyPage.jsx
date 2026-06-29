import LegalLayout from './LegalLayout'

export default function PrivacyPage() {
  return (
    <LegalLayout title="Privacy Policy" updated="June 2026">
      <p>
        This policy explains what NextGen TradeBot collects and how it is used. We aim to
        collect only what is needed to operate the Service.
      </p>
      <h2>Information we collect</h2>
      <p>
        Account data (username, email, hashed password), your paper-trading sessions and
        backtests, and optional brokerage API keys you choose to add. We never store your
        passwords in plaintext.
      </p>
      <h2>How we use it</h2>
      <p>
        To authenticate you, run your paper-trading and research features, send account emails
        (verification and password reset), and improve the Service. We do not sell your
        personal data.
      </p>
      <h2>Brokerage keys</h2>
      <p>
        If you add Alpaca paper-trading keys, they are used solely to place simulated orders on
        your own account. You can remove them at any time from Settings.
      </p>
      <h2>Third parties</h2>
      <p>
        We use third-party providers for market data, brokerage (Alpaca paper), and email
        delivery. Data shared with them is limited to what each function requires.
      </p>
      <h2>Data retention &amp; your rights</h2>
      <p>
        You may request deletion of your account and associated data. Contact the operator of
        your deployment to exercise this right.
      </p>
      <h2>Security</h2>
      <p>
        We use hashed passwords, access tokens, and rate limiting. No system is perfectly
        secure; use a strong, unique password.
      </p>
    </LegalLayout>
  )
}
