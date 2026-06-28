import { useParams, useNavigate } from 'react-router-dom'
import DecisionExplorerModal from '../components/DecisionExplorerModal'

/** Deep-link wrapper: /app/trades/:tradeId opens the Decision Explorer modal. */
export default function TradeDecisionPage() {
  const { tradeId } = useParams()
  const navigate = useNavigate()
  return (
    <DecisionExplorerModal
      tradeId={tradeId}
      onClose={() => navigate(-1)}
    />
  )
}
