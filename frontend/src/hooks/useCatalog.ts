import { useEffect, useState } from 'react'
import { queueApi } from '../api/client'
import type { AppointmentSlot, Branch, BranchQr, Service } from '../api/types'

type Resource<T> = {
  data: T
  loading: boolean
  error: string | null
}

export function useBranches(): Resource<Branch[]> {
  const [state, setState] = useState<Resource<Branch[]>>({ data: [], loading: true, error: null })

  useEffect(() => {
    const controller = new AbortController()
    queueApi.getBranches(controller.signal)
      .then((data) => setState({ data, loading: false, error: null }))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === 'AbortError') return
        setState({ data: [], loading: false, error: error instanceof Error ? error.message : 'Не удалось загрузить отделения' })
      })
    return () => controller.abort()
  }, [])

  return state
}

export function useBranchQr(branchId: string): Resource<BranchQr | null> {
  const [state, setState] = useState<Resource<BranchQr | null> & { branchId: string }>({
    branchId: '', data: null, loading: false, error: null,
  })

  useEffect(() => {
    if (!branchId) return
    const controller = new AbortController()
    queueApi.getBranchQr(branchId, controller.signal)
      .then((data) => setState({ branchId, data, loading: false, error: null }))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === 'AbortError') return
        setState({
          branchId,
          data: null,
          loading: false,
          error: error instanceof Error ? error.message : 'Не удалось создать QR-код',
        })
      })
    return () => controller.abort()
  }, [branchId])

  if (!branchId) return { data: null, loading: false, error: null }
  if (state.branchId !== branchId) return { data: null, loading: true, error: null }
  return { data: state.data, loading: state.loading, error: state.error }
}

export function useServices(branchId: string): Resource<Service[]> {
  const [state, setState] = useState<Resource<Service[]> & { branchId: string }>({
    branchId: '',
    data: [],
    loading: false,
    error: null,
  })

  useEffect(() => {
    if (!branchId) return

    const controller = new AbortController()
    queueApi.getServices(branchId, controller.signal)
      .then((data) => setState({ branchId, data, loading: false, error: null }))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === 'AbortError') return
        setState({
          branchId,
          data: [],
          loading: false,
          error: error instanceof Error ? error.message : 'Не удалось загрузить услуги',
        })
      })
    return () => controller.abort()
  }, [branchId])

  if (!branchId) return { data: [], loading: false, error: null }
  if (state.branchId !== branchId) return { data: [], loading: true, error: null }
  return { data: state.data, loading: state.loading, error: state.error }
}

export function useBranchByCode(code: string): Resource<Branch | null> {
  const [state, setState] = useState<Resource<Branch | null> & { code: string }>({
    code: '', data: null, loading: false, error: null,
  })

  useEffect(() => {
    if (code.length !== 6) return
    const controller = new AbortController()
    queueApi.getBranchByCode(code, controller.signal)
      .then((data) => setState({ code, data, loading: false, error: null }))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === 'AbortError') return
        setState({ code, data: null, loading: false, error: error instanceof Error ? error.message : 'Отделение не найдено' })
      })
    return () => controller.abort()
  }, [code])

  if (code.length !== 6) return { data: null, loading: false, error: null }
  if (state.code !== code) return { data: null, loading: true, error: null }
  return { data: state.data, loading: state.loading, error: state.error }
}

export function useSlots(branchId: string, serviceId: string, date: string): Resource<AppointmentSlot[]> {
  const key = `${branchId}:${serviceId}:${date}`
  const [state, setState] = useState<Resource<AppointmentSlot[]> & { key: string }>({
    key: '', data: [], loading: false, error: null,
  })

  useEffect(() => {
    if (!branchId || !serviceId || !date) return
    const controller = new AbortController()
    queueApi.getSlots(branchId, serviceId, date, controller.signal)
      .then((data) => setState({ key, data, loading: false, error: null }))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === 'AbortError') return
        setState({ key, data: [], loading: false, error: error instanceof Error ? error.message : 'Не удалось загрузить время' })
      })
    return () => controller.abort()
  }, [branchId, serviceId, date, key])

  if (!branchId || !serviceId || !date) return { data: [], loading: false, error: null }
  if (state.key !== key) return { data: [], loading: true, error: null }
  return { data: state.data, loading: state.loading, error: state.error }
}
