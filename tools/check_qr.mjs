#!/usr/bin/env node
import { randomUUID } from 'node:crypto'
import { readFileSync } from 'node:fs'

const baseUrl = (process.argv[2] ?? 'http://127.0.0.1:3000').replace(/\/$/, '')

async function request(path, options = {}) {
  const response = await fetch(`${baseUrl}${path}`, {
    ...options,
    headers: { Accept: 'application/json', ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...(options.headers ?? {}) },
  })
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new Error(`${options.method ?? 'GET'} ${path}: ${response.status} ${JSON.stringify(body)}`)
  return body
}

function nextMessage(socket, timeoutMs = 7000) {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error('WebSocket message timed out')), timeoutMs)
    socket.addEventListener('message', (event) => {
      clearTimeout(timeout)
      resolve(JSON.parse(event.data))
    }, { once: true })
  })
}

function waitForTicket(socket, predicate, timeoutMs = 10000) {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      socket.removeEventListener('message', onMessage)
      reject(new Error('Expected ticket update timed out'))
    }, timeoutMs)
    function onMessage(event) {
      const message = JSON.parse(event.data)
      if (message.type !== 'ticket' || !predicate(message.ticket)) return
      clearTimeout(timeout)
      socket.removeEventListener('message', onMessage)
      resolve(message.ticket)
    }
    socket.addEventListener('message', onMessage)
  })
}

function demoPin() {
  if (process.env.DEMO_STAFF_PIN) return process.env.DEMO_STAFF_PIN
  const line = readFileSync(new URL('../.env', import.meta.url), 'utf8').split(/\r?\n/).find((item) => item.startsWith('DEMO_STAFF_PIN='))
  if (!line) throw new Error('DEMO_STAFF_PIN is missing')
  return line.slice('DEMO_STAFF_PIN='.length).trim()
}

async function selectIdleScenario(branches, pin) {
  for (const branch of branches) {
    const manager = await request('/api/staff/login', {
      method: 'POST',
      body: JSON.stringify({ branch_id: branch.id, employee_code: 'manager-1', pin }),
    })
    const headers = { Authorization: `Bearer ${manager.token}` }
    const dashboard = await request('/api/manager/dashboard', { headers })
    await request('/api/staff/logout', { method: 'POST', headers })

    const busyServiceIds = new Set([
      ...dashboard.unfinished_tickets.map((ticket) => ticket.service_id),
      ...dashboard.windows.flatMap((windowItem) => windowItem.active_ticket ? [windowItem.active_ticket.service_id] : []),
    ])
    const service = dashboard.services.find((item) => item.active && !busyServiceIds.has(item.id))
    const windowItem = dashboard.windows.find((item) => item.status === 'closed')
    if (service && windowItem) return { branch, service, windowId: windowItem.id }
  }
  throw new Error('No idle branch/service pair is available for an isolated QR call test')
}

async function main() {
  const branches = await request('/api/branches')
  const scenario = await selectIdleScenario(branches, demoPin())
  const { branch, service, windowId } = scenario
  const origin = 'http://192.0.2.10:3000'
  const qr = await request(`/api/branches/${branch.id}/queue-qr?public_origin=${encodeURIComponent(origin)}`)
  const target = new URL(qr.join_url)
  if (target.origin !== origin || target.pathname !== '/qr' || target.searchParams.get('branch') !== branch.postal_code) {
    throw new Error(`QR deep-link is invalid: ${qr.join_url}`)
  }
  const svg = await fetch(`${baseUrl}${qr.qr_svg_path}`)
  if (!svg.ok || !(await svg.text()).startsWith('<svg')) throw new Error('QR SVG is unavailable')

  const ticket = await request('/api/queue/join', {
    method: 'POST',
    headers: { 'Idempotency-Key': randomUUID() },
    body: JSON.stringify({ branch_code: branch.postal_code, service_id: service.id }),
  })
  if (ticket.source !== 'qr' || ticket.status !== 'waiting' || !ticket.session_token) {
    throw new Error('QR join did not return an active electronic ticket')
  }

  const socketUrl = new URL(`/api/ws/tickets/${ticket.id}`, baseUrl)
  socketUrl.protocol = socketUrl.protocol === 'https:' ? 'wss:' : 'ws:'
  const socket = new WebSocket(socketUrl)
  await new Promise((resolve, reject) => {
    socket.addEventListener('open', resolve, { once: true })
    socket.addEventListener('error', () => reject(new Error('WebSocket connection failed')), { once: true })
  })
  socket.send(JSON.stringify({ session_token: ticket.session_token }))
  const initial = await nextMessage(socket)
  if (initial.type !== 'ticket' || initial.ticket.id !== ticket.id) throw new Error('WebSocket did not restore the ticket')

  const operator = await request('/api/staff/login', {
    method: 'POST',
    body: JSON.stringify({ branch_id: branch.id, employee_code: 'operator-1', pin: demoPin() }),
  })
  const operatorHeaders = { Authorization: `Bearer ${operator.token}` }
  const windows = await request('/api/staff/windows', { headers: operatorHeaders })
  const windowItem = windows.find((item) => item.id === windowId && item.status === 'closed')
  if (!windowItem) throw new Error('The selected window is no longer available for QR call test')
  await request(`/api/staff/windows/${windowItem.id}/open`, {
    method: 'POST', headers: operatorHeaders, body: JSON.stringify({ service_ids: [service.id] }),
  })

  const calledPromise = waitForTicket(socket, (item) => item.status === 'called')
  const called = await request(`/api/staff/windows/${windowItem.id}/call-next`, { method: 'POST', headers: operatorHeaders })
  if (called.id !== ticket.id) throw new Error(`Operator called another ticket: ${called.id}`)
  const liveCall = await calledPromise
  if (liveCall.window_number !== windowItem.number) {
    throw new Error('Smartphone update did not include the called window number')
  }
  await request(`/api/staff/tickets/${ticket.id}/no-show`, { method: 'POST', headers: operatorHeaders })
  await request(`/api/staff/windows/${windowItem.id}/close`, { method: 'POST', headers: operatorHeaders })
  await request('/api/staff/logout', { method: 'POST', headers: operatorHeaders })
  socket.close()
  console.log('QR smoke test passed: phone origin, branch deep-link, SVG, service ticket, live call with window number')
}

main().catch((error) => {
  console.error(error)
  process.exit(1)
})
