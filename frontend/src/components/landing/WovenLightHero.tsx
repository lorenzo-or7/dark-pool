/**
 * Woven Light Hero — Dhileep Kumar (21st.dev), from the source supplied in the
 * DARK POOL kit. Same torus-knot particle weave, cursor repulsion, spring back
 * to rest, slow Y rotation and staggered text entrance; adapted to the DARK
 * POOL palette and typography.
 *
 * Production changes, without changing the effect:
 * - no allocations in the frame loop (scalar math instead of new Vector3s);
 * - device pixel ratio capped, particle count scaled to the device;
 * - the loop is cancelled on unmount, paused off-screen and in hidden tabs;
 * - geometry, material, renderer and every listener are released;
 * - resize follows the container (ResizeObserver), not the window;
 * - prefers-reduced-motion renders one still frame, no loop;
 * - no WebGL: a static fallback keeps the composition.
 */
import { motion, useAnimation, useReducedMotion } from 'motion/react'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import * as THREE from 'three'
import { EclipseMark } from '@/brand/EclipseMark'
import { Wordmark } from '@/brand/Wordmark'

function particleBudget() {
  const w = window.innerWidth
  const cores = navigator.hardwareConcurrency || 4
  const mem = (navigator as Navigator & { deviceMemory?: number }).deviceMemory ?? 8
  if (w < 640 || cores <= 4 || mem <= 4) return 16000
  if (w < 1200 || cores <= 8) return 30000
  return 50000 // the original density
}

function webglAvailable() {
  try {
    const c = document.createElement('canvas')
    return !!(c.getContext('webgl2') || c.getContext('webgl'))
  } catch {
    return false
  }
}

function WovenCanvas({ onFail }: { onFail: () => void }) {
  const mountRef = useRef<HTMLDivElement>(null)
  const reduce = useReducedMotion()

  useEffect(() => {
    const mount = mountRef.current
    if (!mount) return
    let renderer: THREE.WebGLRenderer
    try {
      renderer = new THREE.WebGLRenderer({ antialias: false, alpha: true, powerPreference: 'high-performance' })
    } catch {
      onFail()
      return
    }
    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(75, 1, 0.1, 1000)
    camera.position.z = 5
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.75))
    mount.appendChild(renderer.domElement)
    renderer.domElement.setAttribute('aria-hidden', 'true')

    const count = particleBudget()
    const positions = new Float32Array(count * 3)
    const original = new Float32Array(count * 3)
    const velocities = new Float32Array(count * 3)
    const colors = new Float32Array(count * 3)

    const knot = new THREE.TorusKnotGeometry(1.5, 0.5, 200, 32)
    const src = knot.attributes.position
    const color = new THREE.Color()
    for (let i = 0; i < count; i++) {
      const v = i % src.count
      const ix = i * 3
      positions[ix] = original[ix] = src.getX(v)
      positions[ix + 1] = original[ix + 1] = src.getY(v)
      positions[ix + 2] = original[ix + 2] = src.getZ(v)
      // DARK POOL palette: volcanic orange threads with a few cool highlights. Normal blending keeps the
    // orange true; additive blending of 50k orange points saturates toward yellow.
      const r = Math.random()
      if (r < 0.08) color.setHSL(0.56, 0.18, 0.55)
      else color.setHSL(0.03 + Math.random() * 0.025, 1, 0.42 + Math.random() * 0.16)
      colors[ix] = color.r
      colors[ix + 1] = color.g
      colors[ix + 2] = color.b
    }
    knot.dispose()

    const geometry = new THREE.BufferGeometry()
    const posAttr = new THREE.BufferAttribute(positions, 3)
    posAttr.setUsage(THREE.DynamicDrawUsage)
    geometry.setAttribute('position', posAttr)
    geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3))
    const material = new THREE.PointsMaterial({
      size: 0.02,
      vertexColors: true,
      blending: THREE.NormalBlending,
      transparent: true,
      opacity: 0.85,
      depthWrite: false,
    })
    const points = new THREE.Points(geometry, material)
    scene.add(points)

    let mx = 0
    let my = 0
    const onMove = (e: PointerEvent) => {
      const r = mount.getBoundingClientRect()
      mx = ((e.clientX - r.left) / r.width) * 2 - 1
      my = -((e.clientY - r.top) / r.height) * 2 + 1
    }
    window.addEventListener('pointermove', onMove, { passive: true })

    const resize = () => {
      const w = mount.clientWidth || window.innerWidth
      const h = mount.clientHeight || window.innerHeight
      camera.aspect = w / h
      camera.updateProjectionMatrix()
      renderer.setSize(w, h, false)
      renderer.domElement.style.width = '100%'
      renderer.domElement.style.height = '100%'
    }
    const ro = new ResizeObserver(resize)
    ro.observe(mount)
    resize()

    const clock = new THREE.Clock()
    let raf = 0
    let visible = true
    let pageVisible = !document.hidden

    const step = () => {
      const t = clock.getElapsedTime()
      const wx = mx * 3
      const wy = my * 3
      for (let i = 0; i < count; i++) {
        const ix = i * 3
        const px = positions[ix]
        const py = positions[ix + 1]
        const pz = positions[ix + 2]
        let vx = velocities[ix]
        let vy = velocities[ix + 1]
        let vz = velocities[ix + 2]
        const dx = px - wx
        const dy = py - wy
        const dz = pz
        const d2 = dx * dx + dy * dy + dz * dz
        if (d2 < 2.25) {
          const dist = Math.sqrt(d2) || 1e-6
          const f = ((1.5 - dist) * 0.01) / dist
          vx += dx * f
          vy += dy * f
          vz += dz * f
        }
        vx = (vx + (original[ix] - px) * 0.001) * 0.95
        vy = (vy + (original[ix + 1] - py) * 0.001) * 0.95
        vz = (vz + (original[ix + 2] - pz) * 0.001) * 0.95
        positions[ix] = px + vx
        positions[ix + 1] = py + vy
        positions[ix + 2] = pz + vz
        velocities[ix] = vx
        velocities[ix + 1] = vy
        velocities[ix + 2] = vz
      }
      posAttr.needsUpdate = true
      points.rotation.y = t * 0.05
      renderer.render(scene, camera)
    }

    const loop = () => {
      step()
      raf = requestAnimationFrame(loop)
    }
    const start = () => {
      if (!raf && visible && pageVisible && !reduce) {
        clock.start()
        raf = requestAnimationFrame(loop)
      }
    }
    const stop = () => {
      cancelAnimationFrame(raf)
      raf = 0
    }

    const io = new IntersectionObserver(([e]) => {
      visible = e.isIntersecting
      if (visible) start()
      else stop()
    })
    io.observe(mount)
    const onVis = () => {
      pageVisible = !document.hidden
      if (pageVisible) start()
      else stop()
    }
    document.addEventListener('visibilitychange', onVis)

    if (reduce) {
      points.rotation.y = 0.35
      renderer.render(scene, camera)
    } else start()

    return () => {
      stop()
      io.disconnect()
      ro.disconnect()
      document.removeEventListener('visibilitychange', onVis)
      window.removeEventListener('pointermove', onMove)
      scene.remove(points)
      geometry.dispose()
      material.dispose()
      renderer.dispose()
      renderer.forceContextLoss()
      renderer.domElement.remove()
    }
  }, [reduce, onFail])

  return <div ref={mountRef} className="absolute inset-0 z-0" />
}

function StaticWeave() {
  return (
    <div className="absolute inset-0 z-0 flex items-center justify-center" aria-hidden>
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(255,65,3,0.10),transparent_55%)]" />
      <EclipseMark className="size-[min(70vw,520px)] opacity-60" flare={false} weight={0.6} title="" />
    </div>
  )
}

const tagline = 'BEYOND THE MARKET.'

export function WovenLightHero({ children, sub }: { children?: ReactNode; sub: string }) {
  const textControls = useAnimation()
  const buttonControls = useAnimation()
  const reduce = useReducedMotion()
  const [gl, setGl] = useState(true)
  const failRef = useRef(() => setGl(false))

  useEffect(() => {
    setGl(webglAvailable())
  }, [])

  useEffect(() => {
    if (reduce) {
      textControls.set({ opacity: 1, y: 0 })
      buttonControls.set({ opacity: 1 })
      return
    }
    void textControls.start((i: number) => ({
      opacity: 1,
      y: 0,
      transition: { delay: i * 0.035 + 0.55, duration: 1.2, ease: [0.2, 0.65, 0.3, 0.9] },
    }))
    void buttonControls.start({ opacity: 1, transition: { delay: 1.6, duration: 1 } })
  }, [textControls, buttonControls, reduce])

  return (
    <section id="top" className="relative flex min-h-[100svh] w-full flex-col items-center justify-center overflow-hidden bg-ink">
      {gl ? <WovenCanvas onFail={failRef.current} /> : <StaticWeave />}
      <div className="pointer-events-none absolute inset-0 z-[1] bg-[radial-gradient(ellipse_at_center,transparent_30%,rgba(0,22,33,0.65)_75%,#001621_100%)]" />
      <div className="relative z-10 flex w-full max-w-5xl flex-col items-center px-4 text-center">
        <div className="pointer-events-none absolute inset-x-0 top-[38%] -z-10 mx-auto h-[70%] max-w-3xl rounded-full bg-ink/70 blur-3xl" aria-hidden />
        <motion.h1 custom={0} initial={{ opacity: 0, y: 50 }} animate={textControls} className="w-full max-w-[860px]">
          <span className="sr-only">DARK POOL</span>
          <Wordmark className="mx-auto h-auto w-full text-fg drop-shadow-[0_0_40px_rgba(0,22,33,0.9)]" />
        </motion.h1>
        <p className="mt-7 font-mono text-[11px] tracking-[0.62em] text-fg/90 sm:text-[13px]" aria-label="Beyond the market.">
          {tagline.split('').map((ch, j) => (
            <motion.span
              key={j}
              custom={j + 4}
              initial={{ opacity: 0, y: 30 }}
              animate={textControls}
              className="inline-block"
              aria-hidden
            >
              {ch === ' ' ? ' ' : ch}
            </motion.span>
          ))}
        </p>
        <motion.p
          custom={tagline.length + 6}
          initial={{ opacity: 0, y: 30 }}
          animate={textControls}
          className="mx-auto mt-6 max-w-xl text-base leading-relaxed text-fg/80 [text-shadow:0_1px_12px_rgba(0,22,33,0.95)] sm:text-lg"
        >
          {sub}
        </motion.p>
        <motion.div initial={{ opacity: 0 }} animate={buttonControls} className="mt-10 flex flex-col items-center gap-3 sm:flex-row">
          {children}
        </motion.div>
      </div>
    </section>
  )
}
