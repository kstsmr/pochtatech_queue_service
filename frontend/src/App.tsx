import { BrowserRouter, Route, Routes } from 'react-router-dom'
import './App.css'
import { AppShell } from './components/AppShell'
import { BookingPage } from './pages/BookingPage'
import { HomePage } from './pages/HomePage'
import { NotFoundPage } from './pages/NotFoundPage'
import { QrEntryPage } from './pages/QrEntryPage'
import { QrStandPage } from './pages/QrStandPage'
import { TicketPage } from './pages/TicketPage'
import { StaffPage } from './pages/StaffPage'
import { ManagerPage } from './pages/ManagerPage'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="staff" element={<StaffPage />} />
        <Route path="manager" element={<ManagerPage />} />
        <Route path="kiosk" element={<QrStandPage kiosk />} />
        <Route element={<AppShell />}>
          <Route index element={<HomePage />} />
          <Route path="book" element={<BookingPage />} />
          <Route path="qr" element={<QrEntryPage />} />
          <Route path="demo/qr" element={<QrStandPage />} />
          <Route path="ticket" element={<TicketPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
