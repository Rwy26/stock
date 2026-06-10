import { Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from './layout/AppShell'
import { RequireAuth } from './layout/RequireAuth'
import { AdminPage } from './pages/AdminPage'
import { AutoBasicPage } from './pages/AutoBasicPage'
import { AutoPlusPage } from './pages/AutoPlusPage'
import { AutoSaPage } from './pages/AutoSaPage'
import { StrategyPage } from './pages/StrategyPage'
import { DashboardPage } from './pages/DashboardPage'
import { LoginPage } from './pages/LoginPage'
import { PortfolioPage } from './pages/PortfolioPage'
import { ProfileSetupPage } from './pages/ProfileSetupPage'
import { RecommendationsPage } from './pages/RecommendationsPage'
import { StockSearchPage } from './pages/StockSearchPage'
import { SvAgentPage } from './pages/SvAgentPage'

import { WatchlistPage } from './pages/WatchlistPage'
import { BolinzerPage } from './pages/BolinzerPage'
import { InvestmentRulesPage } from './pages/InvestmentRulesPage'
import { AiChartPage } from './pages/AiChartPage'
import { AiCachePage } from './pages/AiCachePage'
import { SectorRotationPage } from './pages/SectorRotationPage'
import { PublicShell } from './layout/PublicShell'
import { PublicAiRequestPage } from './pages/public/PublicAiRequestPage'
import { PublicRequestsPage } from './pages/PublicRequestsPage'

export default function App() {
  return (
    <>
      <div className="bg-orb orb-1"></div>
      <div className="bg-orb orb-2"></div>

      <Routes>
        <Route
          element={
            <RequireAuth>
              <AppShell />
            </RequireAuth>
          }
        >
          <Route index element={<DashboardPage />} />
          <Route path="portfolio" element={<PortfolioPage />} />
          <Route path="stock-search" element={<StockSearchPage />} />
          <Route path="recommendations" element={<RecommendationsPage />} />
          <Route path="watchlist" element={<WatchlistPage />} />
          <Route path="strategy" element={<StrategyPage />} />
          <Route path="auto-basic" element={<AutoBasicPage />} />
          <Route path="auto-sa" element={<AutoSaPage />} />
          <Route path="auto-plus" element={<AutoPlusPage />} />
          <Route path="sv-agent" element={<SvAgentPage />} />
          <Route path="admin" element={<AdminPage />} />
          <Route path="bolinzer" element={<BolinzerPage />} />
          <Route path="investment-rules" element={<InvestmentRulesPage />} />
          <Route path="ai-chart" element={<AiChartPage />} />
          <Route path="ai-cache" element={<AiCachePage />} />
          <Route path="sector-rotation" element={<SectorRotationPage />} />
          <Route path="public-requests" element={<PublicRequestsPage />} />
        </Route>

        {/* Public (guest) area — outside RequireAuth. Name+phone gate only. */}
        <Route path="/public" element={<PublicShell />}>
          {/* 종목 추천은 공개 메뉴에서 제외 — 첫 화면은 섹터 나침반 */}
          <Route index element={<Navigate to="/public/sector" replace />} />
          <Route path="sector" element={<SectorRotationPage publicMode />} />
          <Route path="watchlist" element={<WatchlistPage publicMode />} />
          <Route path="ai-request" element={<PublicAiRequestPage />} />
        </Route>

        <Route path="login" element={<LoginPage />} />
        <Route
          path="profile-setup"
          element={
            <RequireAuth>
              <ProfileSetupPage />
            </RequireAuth>
          }
        />

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  )
}
