'use client'
import { AppProvider, useApp } from '@/lib/store'
import Navbar         from '@/components/Navbar'
import UploadScreen   from '@/components/UploadScreen'
import AnalysisScreen from '@/components/AnalysisScreen'
import ReviewScreen   from '@/components/ReviewScreen'
import ReportScreen   from '@/components/ReportScreen'

function App() {
  const { activeScreen } = useApp()
  return (
    <>
      <Navbar />
      {activeScreen === 'upload'   && <UploadScreen />}
      {activeScreen === 'analysis' && <AnalysisScreen />}
      {activeScreen === 'review'   && <ReviewScreen />}
      {activeScreen === 'report'   && <ReportScreen />}
    </>
  )
}

export default function Page() {
  return (
    <AppProvider>
      <App />
    </AppProvider>
  )
}
