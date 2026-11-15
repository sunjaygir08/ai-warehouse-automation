import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

/* ══════════════════════════════════════════════════════════════════════════════
   SMART WAREHOUSE 3D SIMULATION PROTOTYPE
   - Realistic industrial environment matching reference image
   - 10 AMRs with orange base, dark chassis, blue LED strips, cargo cage & box stacks
   - Blue metal storage racks with orange beams and stacked cardboard boxes
   - Yellow floor navigation lanes, green circular waypoints, cyan route lasers
   - Picking workstation (conveyor, monitors, canopy) & Charging docks
   - Isometric & Top-down camera controls with smooth OrbitControls
   - Raycasting interaction for robots & storage racks
   - Flask simulation backend integration (BFS paths, start/pause/reset/speed)
══════════════════════════════════════════════════════════════════════════════ */

const root = document.getElementById('warehouse-scene');
const errorEl = document.getElementById('scene-error');

// Default warehouse configuration matching Flask app backend
const DEFAULT_WAREHOUSE_CONFIG = {
  grid: { rows: 12, cols: 16 },
  station: { row: 10, col: 14 },
  charging: [{ row: 10, col: 1 }, { row: 10, col: 2 }],
  shelves: [
    { row: 2, col: 3, levels: 3 }, { row: 2, col: 4, levels: 3 },
    { row: 2, col: 7, levels: 3 }, { row: 2, col: 8, levels: 3 },
    { row: 2, col: 11, levels: 3 }, { row: 2, col: 12, levels: 3 },
    { row: 5, col: 3, levels: 3 }, { row: 5, col: 4, levels: 3 },
    { row: 5, col: 7, levels: 3 }, { row: 5, col: 8, levels: 3 },
    { row: 5, col: 11, levels: 3 }, { row: 5, col: 12, levels: 3 },
    { row: 8, col: 3, levels: 3 }, { row: 8, col: 4, levels: 3 },
    { row: 8, col: 7, levels: 3 }, { row: 8, col: 8, levels: 3 },
    { row: 8, col: 11, levels: 3 }, { row: 8, col: 12, levels: 3 }
  ]
};

// Scene core variables
let state = null;
let scene, camera, renderer, controls, raycaster;
let worldGroup, floorGroup, rackGroup, robotGroup, pathGroup, gridGroup, stationGroup;
let selectionRing = null;
let selectedRobotId = null;
let selectedRackData = null;
let fallbackCanvas = null;
let fallbackAnimationId = null;
let environmentBuilt = false;
let isAppStarted = false;

// Robot mesh and animation state mapping
// key: robotId -> { group, currentPos, targetPos, currentRotY, targetRotY }
const robotEntities = new Map();
const rackMeshes = [];

// Warehouse grid constants
const CELL_SIZE = 2.2; // meters per grid cell

// Reusable Materials & Textures Cache
const matCache = {};

// ─────────────────────────────────────────────────────────────────────────────
// Procedural Texture Generators (Cached)
// ─────────────────────────────────────────────────────────────────────────────

function createConcreteTexture() {
  if (matCache['_tex_concrete']) return matCache['_tex_concrete'];

  const canvas = document.createElement('canvas');
  canvas.width = 512;
  canvas.height = 512;
  const ctx = canvas.getContext('2d');

  // Base industrial grey concrete
  ctx.fillStyle = '#666c75';
  ctx.fillRect(0, 0, 512, 512);

  // Subtle noise and aggregate specks
  for (let i = 0; i < 30000; i++) {
    const x = Math.random() * 512;
    const y = Math.random() * 512;
    const lum = Math.floor(80 + Math.random() * 60);
    const alpha = 0.04 + Math.random() * 0.06;
    ctx.fillStyle = `rgba(${lum}, ${lum}, ${lum + 4}, ${alpha})`;
    ctx.fillRect(x, y, 1.5, 1.5);
  }

  // Expansion joint lines
  ctx.strokeStyle = 'rgba(40, 45, 52, 0.4)';
  ctx.lineWidth = 2;
  ctx.strokeRect(0, 0, 512, 512);
  ctx.beginPath();
  ctx.moveTo(256, 0); ctx.lineTo(256, 512);
  ctx.moveTo(0, 256); ctx.lineTo(512, 256);
  ctx.stroke();

  const texture = new THREE.CanvasTexture(canvas);
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.RepeatWrapping;
  texture.colorSpace = THREE.SRGBColorSpace;
  matCache['_tex_concrete'] = texture;
  return texture;
}

function createBoxTexture(variant = 0) {
  const cacheKey = `_tex_box_${variant % 4}`;
  if (matCache[cacheKey]) return matCache[cacheKey];

  const canvas = document.createElement('canvas');
  canvas.width = 256;
  canvas.height = 256;
  const ctx = canvas.getContext('2d');

  const shades = ['#b37b46', '#a56f3d', '#be8550', '#9c6635'];
  ctx.fillStyle = shades[variant % shades.length];
  ctx.fillRect(0, 0, 256, 256);

  // Subtle paper grain
  for (let i = 0; i < 2000; i++) {
    ctx.fillStyle = Math.random() > 0.5 ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.05)';
    ctx.fillRect(Math.random() * 256, Math.random() * 256, 2, 2);
  }

  // Packaging tape across the center seam
  ctx.fillStyle = 'rgba(215, 165, 95, 0.55)';
  ctx.fillRect(108, 0, 40, 256);
  ctx.strokeStyle = 'rgba(120, 80, 30, 0.35)';
  ctx.lineWidth = 1;
  ctx.strokeRect(108, 0, 40, 256);

  // Small shipping label / barcode
  ctx.fillStyle = '#f0f3f6';
  ctx.fillRect(25, 30, 55, 38);
  ctx.fillStyle = '#222';
  for (let b = 32; b < 72; b += 4) {
    if (Math.random() > 0.3) ctx.fillRect(b, 35, 2, 20);
  }

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  matCache[cacheKey] = texture;
  return texture;
}

function createGlowDotTexture() {
  if (matCache['_tex_glowdot']) return matCache['_tex_glowdot'];

  const canvas = document.createElement('canvas');
  canvas.width = 128;
  canvas.height = 128;
  const ctx = canvas.getContext('2d');

  const grad = ctx.createRadialGradient(64, 64, 4, 64, 64, 60);
  grad.addColorStop(0, 'rgba(0, 255, 150, 1)');
  grad.addColorStop(0.35, 'rgba(0, 255, 130, 0.85)');
  grad.addColorStop(0.7, 'rgba(0, 230, 110, 0.25)');
  grad.addColorStop(1, 'rgba(0, 230, 110, 0)');

  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, 128, 128);

  const texture = new THREE.CanvasTexture(canvas);
  matCache['_tex_glowdot'] = texture;
  return texture;
}

// ─────────────────────────────────────────────────────────────────────────────
// Material Factory
// ─────────────────────────────────────────────────────────────────────────────

function getSharedMaterial(key, params) {
  if (!matCache[key]) {
    matCache[key] = new THREE.MeshStandardMaterial(params);
  }
  return matCache[key];
}

// ─────────────────────────────────────────────────────────────────────────────
// Coordinate Conversion Function
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Converts backend grid coordinates (row, col) into 3D world space (X, Y, Z).
 * - row: increases along +Z (North to South)
 * - col: increases along +X (West to East)
 * - y: vertical height above floor
 */
function gridToWorld(row, col, y = 0) {
  const rows = state?.grid?.rows || DEFAULT_WAREHOUSE_CONFIG.grid.rows;
  const cols = state?.grid?.cols || DEFAULT_WAREHOUSE_CONFIG.grid.cols;
  const x = (col - cols / 2 + 0.5) * CELL_SIZE;
  const z = (row - rows / 2 + 0.5) * CELL_SIZE;
  return new THREE.Vector3(x, y, z);
}

// ─────────────────────────────────────────────────────────────────────────────
// WebGL Diagnostic Probing & Error Reporting
// ─────────────────────────────────────────────────────────────────────────────

function probeWebGLSupport() {
  const report = {
    webgl2: false,
    webgl1: false,
    vendor: 'Unknown',
    renderer: 'Unknown',
    unmaskedVendor: 'Unknown',
    unmaskedRenderer: 'Unknown',
    errorMessage: null
  };

  if (!window.WebGLRenderingContext) {
    report.errorMessage = 'window.WebGLRenderingContext is undefined in this browser.';
    return report;
  }

  const testCanvas = document.createElement('canvas');
  testCanvas.width = 16;
  testCanvas.height = 16;

  let gl = null;
  // Test WebGL 2 first
  try {
    gl = testCanvas.getContext('webgl2', {
      powerPreference: 'default',
      failIfMajorPerformanceCaveat: false
    });
    if (gl) report.webgl2 = true;
  } catch (e) {
    report.errorMessage = `WebGL2 probe error: ${e.message}`;
  }

  // Test WebGL 1
  if (!gl) {
    try {
      gl = testCanvas.getContext('webgl', {
        powerPreference: 'default',
        failIfMajorPerformanceCaveat: false
      }) || testCanvas.getContext('experimental-webgl');
      if (gl) report.webgl1 = true;
    } catch (e) {
      report.errorMessage = (report.errorMessage ? report.errorMessage + '; ' : '') + `WebGL1 probe error: ${e.message}`;
    }
  }

  if (gl) {
    try {
      report.vendor = gl.getParameter(gl.VENDOR) || 'Unknown';
      report.renderer = gl.getParameter(gl.RENDERER) || 'Unknown';
      const ext = gl.getExtension('WEBGL_debug_renderer_info');
      if (ext) {
        report.unmaskedVendor = gl.getParameter(ext.UNMASKED_VENDOR_WEBGL) || report.vendor;
        report.unmaskedRenderer = gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) || report.renderer;
      }
      const loseExt = gl.getExtension('WEBGL_lose_context');
      if (loseExt) loseExt.loseContext();
    } catch (e) {
      console.warn('[Warehouse 3D] Failed to read debug renderer info:', e);
    }
  } else if (!report.errorMessage) {
    report.errorMessage = 'Neither WebGL2 nor WebGL1 context could be created on test canvas.';
  }

  return report;
}

function showWebGLError(err, probe) {
  if (!errorEl) return;
  const msgEl = document.getElementById('scene-error-msg');
  const detailsEl = document.getElementById('scene-error-details');
  const fallbackBtn = document.getElementById('btn-force-fallback');

  if (msgEl) {
    msgEl.textContent = 'WebGL is unavailable or encountered an initialization error.';
  }
  if (detailsEl) {
    detailsEl.style.display = 'block';
    detailsEl.innerHTML = `
      <strong>Diagnostic Details:</strong><br>
      • Error: ${err?.message || 'Context creation failed'}<br>
      • GPU Renderer: ${probe?.unmaskedRenderer || probe?.renderer || 'Unknown'}<br>
      • GPU Vendor: ${probe?.unmaskedVendor || probe?.vendor || 'Unknown'}<br>
      • WebGL 2 Context: ${probe?.webgl2 ? 'Supported' : 'Not Available'}<br>
      • WebGL 1 Context: ${probe?.webgl1 ? 'Supported' : 'Not Available'}<br>
      ${probe?.errorMessage ? `• Probe message: ${probe.errorMessage}<br>` : ''}
      <em>Tip: Enable hardware acceleration in your browser settings (chrome://settings/system or edge://settings/system).</em>
    `;
  }
  if (fallbackBtn) {
    fallbackBtn.style.display = 'inline-block';
    fallbackBtn.onclick = () => {
      hideWebGLError();
      initFallback2D();
    };
  }

  errorEl.removeAttribute('hidden');
  errorEl.style.removeProperty('display');
  errorEl.classList.add('visible');
}

function hideWebGLError() {
  if (errorEl) {
    errorEl.setAttribute('hidden', '');
    errorEl.style.display = 'none';
    errorEl.classList.remove('visible');
  }
}

function getSafeViewportDimensions() {
  const rect = root?.getBoundingClientRect();
  const width = Math.max(root?.clientWidth || rect?.width || root?.parentElement?.clientWidth || 800, 300);
  const height = Math.max(root?.clientHeight || rect?.height || 650, 300);
  return { width, height, aspect: width / height };
}

// ─────────────────────────────────────────────────────────────────────────────
// Scene & Renderer Setup
// ─────────────────────────────────────────────────────────────────────────────

function initThreeScene() {
  if (!root) {
    console.error('[Warehouse 3D] Critical: Container #warehouse-scene not found in DOM.');
    return false;
  }

  if (renderer) {
    console.log('[Warehouse 3D] Renderer already initialized.');
    return true;
  }

  const probe = probeWebGLSupport();
  console.log('[Warehouse 3D] WebGL Support Probe:', probe);

  const { width, height, aspect } = getSafeViewportDimensions();
  console.log(`[Warehouse 3D] Canvas container dimensions: ${width}x${height} (aspect: ${aspect.toFixed(2)})`);

  const contextAttributes = {
    antialias: true,
    alpha: false,
    powerPreference: 'default',
    failIfMajorPerformanceCaveat: false,
    preserveDrawingBuffer: false
  };

  let rendererInstance = null;
  let initError = null;

  // Attempt 1: Standard Three.js WebGLRenderer (WebGL 2)
  try {
    rendererInstance = new THREE.WebGLRenderer(contextAttributes);
    console.log('[Warehouse 3D] Successfully initialized THREE.WebGLRenderer (WebGL2).');
  } catch (err1) {
    console.warn('[Warehouse 3D] THREE.WebGLRenderer initialization failed:', err1);
    initError = err1;

    // Attempt 2: Fallback to THREE.WebGL1Renderer if available
    if (typeof THREE.WebGL1Renderer === 'function') {
      try {
        console.log('[Warehouse 3D] Attempting secondary fallback with THREE.WebGL1Renderer...');
        rendererInstance = new THREE.WebGL1Renderer(contextAttributes);
        console.log('[Warehouse 3D] Successfully initialized THREE.WebGL1Renderer (WebGL1 fallback).');
        initError = null;
      } catch (err2) {
        console.error('[Warehouse 3D] THREE.WebGL1Renderer initialization failed:', err2);
        initError = err2;
      }
    }
  }

  // If renderer could not be created, display detailed diagnostics & fallback
  if (!rendererInstance) {
    console.error('[Warehouse 3D] All WebGL renderer initialization attempts failed:', initError);
    showWebGLError(initError, probe);
    initFallback2D();
    return true; // continue running simulation with fallback canvas
  }

  renderer = rendererInstance;
  hideWebGLError();

  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setSize(width, height);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.15;

  // Clear any existing canvas before appending
  const existingCanvases = root.querySelectorAll('canvas');
  existingCanvases.forEach(c => root.removeChild(c));
  root.appendChild(renderer.domElement);

  scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0a131f);
  scene.fog = new THREE.FogExp2(0x0a131f, 0.012);

  // Camera setup - Isometric perspective matching reference photo
  camera = new THREE.PerspectiveCamera(38, aspect, 0.5, 200);
  camera.position.set(22, 25, 26);

  // OrbitControls
  controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(0, 0, 0);
  controls.enableDamping = true;
  controls.dampingFactor = 0.05;
  controls.maxPolarAngle = Math.PI / 2.05; // Prevent viewing below floor
  controls.minDistance = 6;
  controls.maxDistance = 80;

  // Industrial Warehouse Lighting
  const ambientLight = new THREE.AmbientLight(0xd6e5f7, 1.4);
  scene.add(ambientLight);

  const mainSun = new THREE.DirectionalLight(0xffffff, 2.0);
  mainSun.position.set(15, 30, 18);
  mainSun.castShadow = true;
  mainSun.shadow.mapSize.set(2048, 2048);
  mainSun.shadow.camera.near = 5;
  mainSun.shadow.camera.far = 70;
  const d = 25;
  mainSun.shadow.camera.left = -d;
  mainSun.shadow.camera.right = d;
  mainSun.shadow.camera.top = d;
  mainSun.shadow.camera.bottom = -d;
  mainSun.shadow.bias = -0.0005;
  scene.add(mainSun);

  // Cool industrial fill light
  const fillLight = new THREE.DirectionalLight(0x78a6db, 1.1);
  fillLight.position.set(-18, 20, -15);
  scene.add(fillLight);

  // Warm overhead bay accent
  const overheadBayLight = new THREE.PointLight(0xffecd2, 0.8, 40);
  overheadBayLight.position.set(0, 14, 0);
  scene.add(overheadBayLight);

  // Raycaster for user interaction
  raycaster = new THREE.Raycaster();
  renderer.domElement.addEventListener('click', handleSceneClick);

  // Window resize & ResizeObserver on viewport container
  window.addEventListener('resize', handleResize);
  if (window.ResizeObserver) {
    const ro = new ResizeObserver(() => handleResize());
    ro.observe(root);
  }

  // Setup Root Groups
  worldGroup = new THREE.Group(); scene.add(worldGroup);
  floorGroup = new THREE.Group(); worldGroup.add(floorGroup);
  gridGroup = new THREE.Group(); worldGroup.add(gridGroup);
  rackGroup = new THREE.Group(); worldGroup.add(rackGroup);
  stationGroup = new THREE.Group(); worldGroup.add(stationGroup);
  pathGroup = new THREE.Group(); worldGroup.add(pathGroup);
  robotGroup = new THREE.Group(); worldGroup.add(robotGroup);

  createSelectionRing();

  // Animation Loop via renderer.setAnimationLoop
  renderer.setAnimationLoop(renderFrame);

  handleResize();
  return true;
}

// ─────────────────────────────────────────────────────────────────────────────
// Selection Ring (Pulsing highlight beneath selected robot)
// ─────────────────────────────────────────────────────────────────────────────

function createSelectionRing() {
  const ringGeo = new THREE.RingGeometry(0.85, 1.05, 32);
  ringGeo.rotateX(-Math.PI / 2);
  const ringMat = new THREE.MeshBasicMaterial({
    color: 0x00f0ff,
    side: THREE.DoubleSide,
    transparent: true,
    opacity: 0.9
  });
  selectionRing = new THREE.Mesh(ringGeo, ringMat);
  selectionRing.position.set(0, 0.025, 0);
  selectionRing.visible = false;
  scene.add(selectionRing);
}

// ─────────────────────────────────────────────────────────────────────────────
// Static Environment Builder (Floor, Navigation Lanes, Racks, Stations)
// ─────────────────────────────────────────────────────────────────────────────

function buildWarehouseEnvironment() {
  if (!worldGroup) return;

  const cfg = DEFAULT_WAREHOUSE_CONFIG;
  const rows = state?.grid?.rows || cfg.grid.rows;
  const cols = state?.grid?.cols || cfg.grid.cols;
  const floorWidth = cols * CELL_SIZE + 2.0;
  const floorDepth = rows * CELL_SIZE + 2.0;

  // Clear existing static structures without destroying group references
  floorGroup.clear();
  gridGroup.clear();
  rackGroup.clear();
  stationGroup.clear();
  rackMeshes.length = 0;

  // 1. Concrete Warehouse Floor
  const floorTex = createConcreteTexture();
  floorTex.repeat.set(cols / 2, rows / 2);
  const floorMat = getSharedMaterial('concreteFloor', {
    map: floorTex,
    roughness: 0.38,
    metalness: 0.12,
    color: 0xcfd4dc
  });
  const floorGeo = new THREE.BoxGeometry(floorWidth, 0.3, floorDepth);
  const floor = new THREE.Mesh(floorGeo, floorMat);
  floor.position.set(0, -0.15, 0);
  floor.receiveShadow = true;
  floorGroup.add(floor);

  // Warehouse Floor Border Lip (Industrial curb)
  const curbMat = getSharedMaterial('curb', { color: 0x3a424d, roughness: 0.8 });
  const curbHeight = 0.2;
  const curbThick = 0.25;
  for (const z of [-floorDepth / 2, floorDepth / 2]) {
    const curb = new THREE.Mesh(new THREE.BoxGeometry(floorWidth + curbThick * 2, curbHeight, curbThick), curbMat);
    curb.position.set(0, curbHeight / 2, z);
    floorGroup.add(curb);
  }
  for (const x of [-floorWidth / 2, floorWidth / 2]) {
    const curb = new THREE.Mesh(new THREE.BoxGeometry(curbThick, curbHeight, floorDepth), curbMat);
    curb.position.set(x, curbHeight / 2, 0);
    floorGroup.add(curb);
  }

  // 2. Yellow Navigation Lanes & Grid Markings
  buildNavigationLanes(rows, cols);

  // 3. Storage Pallet Racks (Industrial Blue & Orange)
  buildStorageRacks();

  // 4. Stations (Picking Station & Charging Docks)
  buildPickingStation();
  buildChargingDocks();

  environmentBuilt = true;
}

/**
 * Builds the bold yellow navigation highway lanes and cell intersection grid
 * matching the warehouse operations layout.
 */
function buildNavigationLanes(rows, cols) {
  const yellowLineMat = getSharedMaterial('yellowLanes', {
    color: 0xf5b300,
    roughness: 0.3,
    metalness: 0.1
  });

  const lineWidth = 0.09;
  const lineElevation = 0.008;

  // Outer yellow safety boundary around perimeter
  const pWidth = cols * CELL_SIZE;
  const pDepth = rows * CELL_SIZE;
  const halfW = pWidth / 2;
  const halfD = pDepth / 2;

  // Horizontal perimeter lines
  for (const z of [-halfD, halfD]) {
    const line = new THREE.Mesh(new THREE.BoxGeometry(pWidth, 0.005, lineWidth * 1.5), yellowLineMat);
    line.position.set(0, lineElevation, z);
    gridGroup.add(line);
  }
  // Vertical perimeter lines
  for (const x of [-halfW, halfW]) {
    const line = new THREE.Mesh(new THREE.BoxGeometry(lineWidth * 1.5, 0.005, pDepth), yellowLineMat);
    line.position.set(x, lineElevation, 0);
    gridGroup.add(line);
  }

  // Primary navigation aisle lanes across the warehouse
  for (let r = 0; r <= rows; r++) {
    const z = (r - rows / 2) * CELL_SIZE;
    const line = new THREE.Mesh(new THREE.BoxGeometry(pWidth, 0.004, lineWidth), yellowLineMat);
    line.position.set(0, lineElevation, z);
    gridGroup.add(line);
  }

  for (let c = 0; c <= cols; c++) {
    const x = (c - cols / 2) * CELL_SIZE;
    const line = new THREE.Mesh(new THREE.BoxGeometry(lineWidth, 0.004, pDepth), yellowLineMat);
    line.position.set(x, lineElevation, 0);
    gridGroup.add(line);
  }
}

/**
 * Builds realistic industrial pallet storage racks:
 * - Royal Blue vertical metal ladder frames with diagonal bracings (#165899)
 * - Industrial Orange load beams (#eb5f12) supporting 3 shelf levels
 * - Pallets and varied brown cardboard boxes stacked realistically
 */
function buildStorageRacks() {
  const blueFrameMat = getSharedMaterial('rackBlue', { color: 0x165899, roughness: 0.45, metalness: 0.55 });
  const orangeBeamMat = getSharedMaterial('rackOrange', { color: 0xeb5f12, roughness: 0.4, metalness: 0.45 });
  const palletWoodMat = getSharedMaterial('palletWood', { color: 0x8a633b, roughness: 0.85, metalness: 0.05 });

  const boxTextures = [createBoxTexture(0), createBoxTexture(1), createBoxTexture(2), createBoxTexture(3)];
  const boxMaterials = boxTextures.map(tex => new THREE.MeshStandardMaterial({
    map: tex,
    roughness: 0.75,
    metalness: 0.05
  }));

  const rackWidth = CELL_SIZE * 0.92;
  const rackDepth = CELL_SIZE * 0.92;
  const rackHeight = 3.6;
  const postSize = 0.08;
  const levels = [0.8, 1.85, 2.9];

  const postGeo = new THREE.BoxGeometry(postSize, rackHeight, postSize);
  const beamXGeo = new THREE.BoxGeometry(rackWidth, 0.12, 0.05);
  const beamZGeo = new THREE.BoxGeometry(0.05, 0.12, rackDepth);
  const shelfBaseGeo = new THREE.BoxGeometry(rackWidth * 0.96, 0.04, rackDepth * 0.96);
  const palletGeo = new THREE.BoxGeometry(rackWidth * 0.44, 0.07, rackDepth * 0.44);

  const shelves = state?.shelves || DEFAULT_WAREHOUSE_CONFIG.shelves;
  shelves.forEach((shelf, sIdx) => {
    const rack = new THREE.Group();
    const pos = gridToWorld(shelf.row, shelf.col, 0);
    rack.position.set(pos.x, 0, pos.z);

    const hx = rackWidth / 2 - postSize / 2;
    const hz = rackDepth / 2 - postSize / 2;
    const postPositions = [
      [-hx, rackHeight / 2, -hz],
      [hx, rackHeight / 2, -hz],
      [-hx, rackHeight / 2, hz],
      [hx, rackHeight / 2, hz]
    ];
    postPositions.forEach(p => {
      const post = new THREE.Mesh(postGeo, blueFrameMat);
      post.position.set(...p);
      post.castShadow = true;
      post.receiveShadow = true;
      rack.add(post);
    });

    const rungGeo = new THREE.BoxGeometry(postSize * 0.7, 0.035, rackDepth);
    for (let h = 0.4; h < rackHeight; h += 0.5) {
      for (const rx of [-hx, hx]) {
        const rung = new THREE.Mesh(rungGeo, blueFrameMat);
        rung.position.set(rx, h, 0);
        rack.add(rung);
      }
    }

    levels.forEach((lvlY, lvlIdx) => {
      const beamFront = new THREE.Mesh(beamXGeo, orangeBeamMat);
      beamFront.position.set(0, lvlY, hz);
      beamFront.castShadow = true;
      rack.add(beamFront);

      const beamBack = new THREE.Mesh(beamXGeo, orangeBeamMat);
      beamBack.position.set(0, lvlY, -hz);
      beamBack.castShadow = true;
      rack.add(beamBack);

      const beamLeft = new THREE.Mesh(beamZGeo, orangeBeamMat);
      beamLeft.position.set(-hx, lvlY, 0);
      rack.add(beamLeft);

      const beamRight = new THREE.Mesh(beamZGeo, orangeBeamMat);
      beamRight.position.set(hx, lvlY, 0);
      rack.add(beamRight);

      const shelfDeck = new THREE.Mesh(shelfBaseGeo, blueFrameMat);
      shelfDeck.position.set(0, lvlY - 0.03, 0);
      shelfDeck.receiveShadow = true;
      rack.add(shelfDeck);

      const offsets = [
        [-rackWidth * 0.23, -rackDepth * 0.23],
        [rackWidth * 0.23, -rackDepth * 0.23],
        [-rackWidth * 0.23, rackDepth * 0.23],
        [rackWidth * 0.23, rackDepth * 0.23]
      ];

      offsets.forEach(([ox, oz], qIdx) => {
        const pallet = new THREE.Mesh(palletGeo, palletWoodMat);
        pallet.position.set(ox, lvlY + 0.045, oz);
        pallet.receiveShadow = true;
        rack.add(pallet);

        const boxH = 0.42 + ((sIdx + lvlIdx + qIdx) % 3) * 0.08;
        const boxGeo = new THREE.BoxGeometry(0.38, boxH, 0.38);
        const mat = boxMaterials[(sIdx + lvlIdx + qIdx) % boxMaterials.length];
        const boxMesh = new THREE.Mesh(boxGeo, mat);
        boxMesh.position.set(ox, lvlY + 0.08 + boxH / 2, oz);
        boxMesh.castShadow = true;
        boxMesh.receiveShadow = true;
        rack.add(boxMesh);
      });
    });

    rack.userData = {
      isRack: true,
      row: shelf.row,
      col: shelf.col,
      levels: shelf.levels || 3,
      id: `RACK-${shelf.row}-${shelf.col}`
    };

    const hitBox = new THREE.Mesh(
      new THREE.BoxGeometry(rackWidth, rackHeight, rackDepth),
      new THREE.MeshBasicMaterial({ visible: false })
    );
    hitBox.position.set(0, rackHeight / 2, 0);
    hitBox.userData = rack.userData;
    rack.add(hitBox);

    rackMeshes.push(hitBox);
    rackGroup.add(rack);
  });
}

/**
 * Builds the Picking / Dispatch station matching the reference image
 */
function buildPickingStation() {
  const station = state?.station || DEFAULT_WAREHOUSE_CONFIG.station;
  if (!station) return;
  const pos = gridToWorld(station.row, station.col, 0);

  const stGroup = new THREE.Group();
  stGroup.position.set(pos.x, 0, pos.z);

  const deskMat = getSharedMaterial('stationDesk', { color: 0x117a8b, roughness: 0.3, metalness: 0.5 });
  const rollerMat = getSharedMaterial('rollerMetal', { color: 0xb5bcc7, roughness: 0.25, metalness: 0.85 });
  const screenMat = getSharedMaterial('stationScreen', { color: 0x05131d, emissive: 0x00d9ff, emissiveIntensity: 0.4 });
  const yellowStripeMat = getSharedMaterial('hazardYellow', { color: 0xf5b300, roughness: 0.4 });

  const safetyPad = new THREE.Mesh(
    new THREE.BoxGeometry(CELL_SIZE * 1.5, 0.006, CELL_SIZE * 1.2),
    yellowStripeMat
  );
  safetyPad.position.set(0, 0.006, 0);
  stGroup.add(safetyPad);

  const deskTop = new THREE.Mesh(new THREE.BoxGeometry(1.6, 0.08, 0.9), deskMat);
  deskTop.position.set(-0.4, 0.88, 0);
  deskTop.castShadow = true;
  stGroup.add(deskTop);

  for (const dx of [-1.1, 0.3]) {
    for (const dz of [-0.38, 0.38]) {
      const leg = new THREE.Mesh(new THREE.CylinderGeometry(0.035, 0.035, 0.88, 12), deskMat);
      leg.position.set(dx, 0.44, dz);
      stGroup.add(leg);
    }
  }

  const convWidth = 1.3;
  const convDepth = 0.55;
  const convHeight = 0.82;
  const convFrame = new THREE.Mesh(new THREE.BoxGeometry(convWidth, 0.08, convDepth), deskMat);
  convFrame.position.set(0.9, convHeight, 0);
  stGroup.add(convFrame);

  const rollerGeo = new THREE.CylinderGeometry(0.025, 0.025, convDepth * 0.9, 12);
  rollerGeo.rotateX(Math.PI / 2);
  for (let rx = -convWidth / 2 + 0.1; rx <= convWidth / 2 - 0.1; rx += 0.14) {
    const roller = new THREE.Mesh(rollerGeo, rollerMat);
    roller.position.set(0.9 + rx, convHeight + 0.05, 0);
    stGroup.add(roller);
  }

  const boxMat = getSharedMaterial('stationBox', { color: 0xb57c45, roughness: 0.7 });
  for (const [bx, bz] of [[0.6, 0], [1.1, 0.05]]) {
    const parcel = new THREE.Mesh(new THREE.BoxGeometry(0.32, 0.24, 0.35), boxMat);
    parcel.position.set(bx, convHeight + 0.18, bz);
    parcel.castShadow = true;
    stGroup.add(parcel);
  }

  for (const mx of [-0.65, -0.15]) {
    const stand = new THREE.Mesh(new THREE.BoxGeometry(0.03, 0.22, 0.03), deskMat);
    stand.position.set(mx, 1.02, -0.15);
    stGroup.add(stand);

    const screen = new THREE.Mesh(new THREE.BoxGeometry(0.42, 0.26, 0.03), screenMat);
    screen.position.set(mx, 1.16, -0.15);
    stGroup.add(screen);
  }

  const archMat = getSharedMaterial('canopyArch', { color: 0x117a8b, metalness: 0.7, roughness: 0.3 });
  const glowLightMat = new THREE.MeshBasicMaterial({ color: 0x00f0ff });

  const archPostL = new THREE.Mesh(new THREE.BoxGeometry(0.05, 1.6, 0.05), archMat);
  archPostL.position.set(-1.15, 1.68, -0.4);
  stGroup.add(archPostL);

  const archPostR = new THREE.Mesh(new THREE.BoxGeometry(0.05, 1.6, 0.05), archMat);
  archPostR.position.set(0.35, 1.68, -0.4);
  stGroup.add(archPostR);

  const archBar = new THREE.Mesh(new THREE.BoxGeometry(1.6, 0.06, 0.55), archMat);
  archBar.position.set(-0.4, 2.48, -0.15);
  stGroup.add(archBar);

  const canopyGlow = new THREE.Mesh(new THREE.BoxGeometry(1.4, 0.02, 0.08), glowLightMat);
  canopyGlow.position.set(-0.4, 2.44, -0.15);
  stGroup.add(canopyGlow);

  stationGroup.add(stGroup);
}

/**
 * Builds designated AMR charging docks matching reference image
 */
function buildChargingDocks() {
  const charging = state?.charging || DEFAULT_WAREHOUSE_CONFIG.charging;
  if (!charging) return;

  const dockHoodMat = getSharedMaterial('dockHood', { color: 0xd8e3e8, roughness: 0.35, metalness: 0.4 });
  const dockInteriorMat = getSharedMaterial('dockInner', { color: 0x15353d, roughness: 0.6 });
  const greenLedMat = new THREE.MeshBasicMaterial({ color: 0x00ff88 });
  const padMat = getSharedMaterial('chargePad', { color: 0x147963, roughness: 0.4, metalness: 0.2 });

  charging.forEach(dock => {
    const pos = gridToWorld(dock.row, dock.col, 0);
    const dGroup = new THREE.Group();
    dGroup.position.set(pos.x, 0, pos.z);

    const pad = new THREE.Mesh(new THREE.BoxGeometry(CELL_SIZE * 0.95, 0.008, CELL_SIZE * 0.95), padMat);
    pad.position.set(0, 0.004, 0);
    pad.receiveShadow = true;
    dGroup.add(pad);

    const hoodWidth = 1.3;
    const hoodHeight = 1.65;
    const hoodDepth = 0.85;

    const shell = new THREE.Mesh(new THREE.BoxGeometry(hoodWidth, hoodHeight, hoodDepth), dockHoodMat);
    shell.position.set(0, hoodHeight / 2, -0.3);
    shell.castShadow = true;
    dGroup.add(shell);

    const cavity = new THREE.Mesh(new THREE.BoxGeometry(hoodWidth * 0.8, hoodHeight * 0.78, 0.5), dockInteriorMat);
    cavity.position.set(0, hoodHeight * 0.42, 0.05);
    dGroup.add(cavity);

    const ledBar = new THREE.Mesh(new THREE.BoxGeometry(hoodWidth * 0.65, 0.05, 0.02), greenLedMat);
    ledBar.position.set(0, hoodHeight - 0.18, 0.13);
    dGroup.add(ledBar);

    stationGroup.add(dGroup);
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// Reusable AMR 3D Model Factory (MATCHING REFERENCE IMAGE)
// ─────────────────────────────────────────────────────────────────────────────

function createRobotMesh(robotId) {
  const group = new THREE.Group();

  const orangeBaseMat = getSharedMaterial('amrOrange', { color: 0xff6600, roughness: 0.35, metalness: 0.4 });
  const darkChassisMat = getSharedMaterial('amrDarkChassis', { color: 0x1a2129, roughness: 0.55, metalness: 0.7 });
  const wheelMat = getSharedMaterial('amrWheel', { color: 0x0d1115, roughness: 0.8, metalness: 0.2 });
  const blueLedMat = new THREE.MeshBasicMaterial({ color: 0x00f0ff });
  const cageBarMat = getSharedMaterial('amrCage', { color: 0x1c2126, roughness: 0.4, metalness: 0.85 });
  const boxTex = createBoxTexture(parseInt(robotId.replace(/\D/g, '') || '0', 10));
  const boxMat = new THREE.MeshStandardMaterial({ map: boxTex, roughness: 0.75, metalness: 0.05 });

  const baseW = 1.35;
  const baseL = 1.15;
  const baseH = 0.28;

  // 1. Lower Chassis Bumper
  const bumperH = 0.12;
  const bumper = new THREE.Mesh(new THREE.BoxGeometry(baseW, bumperH, baseL), darkChassisMat);
  bumper.position.set(0, bumperH / 2 + 0.03, 0);
  bumper.castShadow = true;
  bumper.receiveShadow = true;
  group.add(bumper);

  // 2. Main Orange Body
  const mainBody = new THREE.Mesh(new THREE.BoxGeometry(baseW * 0.98, baseH, baseL * 0.98), orangeBaseMat);
  mainBody.position.set(0, bumperH + baseH / 2, 0);
  mainBody.castShadow = true;
  group.add(mainBody);

  // 3. Glowing Blue LED Front Light Bar
  const ledFront = new THREE.Mesh(new THREE.BoxGeometry(baseW * 0.65, 0.04, 0.02), blueLedMat);
  ledFront.position.set(0, bumperH + baseH * 0.65, -baseL / 2 - 0.01);
  group.add(ledFront);

  for (const sx of [-baseW / 2 - 0.01, baseW / 2 + 0.01]) {
    const ledSide = new THREE.Mesh(new THREE.BoxGeometry(0.02, 0.03, baseL * 0.45), blueLedMat);
    ledSide.position.set(sx, bumperH + baseH * 0.65, 0);
    group.add(ledSide);
  }

  // 4. Wheels
  const wheelGeo = new THREE.CylinderGeometry(0.07, 0.07, 0.06, 14);
  wheelGeo.rotateZ(Math.PI / 2);
  const wheelOffsets = [
    [-baseW / 2 + 0.04, 0.07, -baseL * 0.28],
    [baseW / 2 - 0.04, 0.07, -baseL * 0.28],
    [-baseW / 2 + 0.04, 0.07, baseL * 0.28],
    [baseW / 2 - 0.04, 0.07, baseL * 0.28]
  ];
  wheelOffsets.forEach(([wx, wy, wz]) => {
    const wheel = new THREE.Mesh(wheelGeo, wheelMat);
    wheel.position.set(wx, wy, wz);
    group.add(wheel);
  });

  // 5. Top Cargo Tower (Black Tubular Metal Cage)
  const cageGroup = new THREE.Group();
  const cageW = baseW * 0.72;
  const cageL = baseL * 0.75;
  const cageH = 1.05;
  const cagePostSize = 0.035;
  const cageBaseY = bumperH + baseH;

  const postGeo = new THREE.BoxGeometry(cagePostSize, cageH, cagePostSize);
  const chx = cageW / 2 - cagePostSize / 2;
  const chz = cageL / 2 - cagePostSize / 2;
  [
    [-chx, cageBaseY + cageH / 2, -chz],
    [chx, cageBaseY + cageH / 2, -chz],
    [-chx, cageBaseY + cageH / 2, chz],
    [chx, cageBaseY + cageH / 2, chz]
  ].forEach(cp => {
    const pMesh = new THREE.Mesh(postGeo, cageBarMat);
    pMesh.position.set(...cp);
    pMesh.castShadow = true;
    cageGroup.add(pMesh);
  });

  const railXGeo = new THREE.BoxGeometry(cageW, 0.025, cagePostSize);
  const railZGeo = new THREE.BoxGeometry(cagePostSize, 0.025, cageL);
  for (const rLvl of [0.35, 0.7, 1.02]) {
    for (const rz of [-chz, chz]) {
      const rx = new THREE.Mesh(railXGeo, cageBarMat);
      rx.position.set(0, cageBaseY + rLvl, rz);
      cageGroup.add(rx);
    }
    for (const rx of [-chx, chx]) {
      const rz = new THREE.Mesh(railZGeo, cageBarMat);
      rz.position.set(rx, cageBaseY + rLvl, 0);
      cageGroup.add(rz);
    }
  }

  // 6. Stack of Cardboard Boxes Inside Cage (Visible when robot is carrying)
  const boxStackGroup = new THREE.Group();
  const boxDimW = (cageW - 0.08) / 2;
  const boxDimL = (cageL - 0.08) / 2;
  const bHeight = 0.38;

  for (const ox of [-boxDimW / 2, boxDimW / 2]) {
    for (const oz of [-boxDimL / 2, boxDimL / 2]) {
      const box = new THREE.Mesh(new THREE.BoxGeometry(boxDimW * 0.95, bHeight, boxDimL * 0.95), boxMat);
      box.position.set(ox, cageBaseY + bHeight / 2 + 0.02, oz);
      box.castShadow = true;
      boxStackGroup.add(box);
    }
  }

  for (const ox of [-boxDimW / 2, boxDimW / 2]) {
    for (const oz of [-boxDimL / 2, boxDimL / 2]) {
      const box = new THREE.Mesh(new THREE.BoxGeometry(boxDimW * 0.95, bHeight * 0.9, boxDimL * 0.95), boxMat);
      box.position.set(ox, cageBaseY + bHeight + (bHeight * 0.9) / 2 + 0.04, oz);
      box.castShadow = true;
      boxStackGroup.add(box);
    }
  }
  boxStackGroup.visible = false;
  cageGroup.add(boxStackGroup);
  group.add(cageGroup);

  // 7. Robot ID Plate
  const idCanvas = document.createElement('canvas');
  idCanvas.width = 128;
  idCanvas.height = 64;
  const idCtx = idCanvas.getContext('2d');
  idCtx.fillStyle = '#ff6600';
  idCtx.fillRect(0, 0, 128, 64);
  idCtx.fillStyle = '#ffffff';
  idCtx.font = 'bold 36px sans-serif';
  idCtx.textAlign = 'center';
  idCtx.textBaseline = 'middle';
  idCtx.fillText(robotId, 64, 34);

  const idTex = new THREE.CanvasTexture(idCanvas);
  const idPlate = new THREE.Mesh(
    new THREE.PlaneGeometry(0.38, 0.19),
    new THREE.MeshBasicMaterial({ map: idTex, transparent: true })
  );
  idPlate.rotation.x = -Math.PI / 2;
  idPlate.position.set(0, cageBaseY + 0.01, baseL * 0.35);
  group.add(idPlate);

  const hitMesh = new THREE.Mesh(
    new THREE.BoxGeometry(baseW * 1.1, cageH + baseH + bumperH, baseL * 1.1),
    new THREE.MeshBasicMaterial({ visible: false })
  );
  hitMesh.position.set(0, (cageH + baseH + bumperH) / 2, 0);
  hitMesh.userData = { robotId };
  group.add(hitMesh);

  group.userData = {
    robotId,
    hitMesh,
    boxStackGroup,
    orangeBaseMat
  };

  robotGroup.add(group);
  return group;
}

// ─────────────────────────────────────────────────────────────────────────────
// Navigation Waypoints & Cyan Route Visualization
// ─────────────────────────────────────────────────────────────────────────────

function updateNavigationVisuals() {
  if (!pathGroup) return;
  pathGroup.clear();

  const showPaths = document.getElementById('sim-paths')?.checked ?? true;
  if (!showPaths || !state?.robots) return;

  const glowDotTex = createGlowDotTexture();
  const waypointGeo = new THREE.PlaneGeometry(0.48, 0.48);
  waypointGeo.rotateX(-Math.PI / 2);
  const waypointMat = new THREE.MeshBasicMaterial({
    map: glowDotTex,
    transparent: true,
    opacity: 0.95,
    depthWrite: false
  });

  const lineMat = new THREE.LineBasicMaterial({
    color: 0x00f0ff,
    linewidth: 3,
    transparent: true,
    opacity: 0.85
  });

  const drawnWaypoints = new Set();

  state.robots.forEach(robot => {
    const pathCoords = [];

    const currPos = gridToWorld(robot.row, robot.col, 0.018);
    pathCoords.push(currPos);

    if (robot.path && robot.path.length > 0) {
      const remaining = robot.path.slice(robot.path_index);
      remaining.forEach(pt => {
        const wpPos = gridToWorld(pt.row, pt.col, 0.018);
        pathCoords.push(wpPos);

        const wpKey = `${pt.row},${pt.col}`;
        if (!drawnWaypoints.has(wpKey)) {
          drawnWaypoints.add(wpKey);
          const wpMesh = new THREE.Mesh(waypointGeo, waypointMat);
          wpMesh.position.set(wpPos.x, 0.019, wpPos.z);
          pathGroup.add(wpMesh);
        }
      });
    }

    if (pathCoords.length >= 2) {
      const lineGeo = new THREE.BufferGeometry().setFromPoints(pathCoords);
      const pathLine = new THREE.Line(lineGeo, lineMat);
      pathGroup.add(pathLine);
    }
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// State Application & Synchronization with Flask Backend
// ─────────────────────────────────────────────────────────────────────────────

function applySimulationState(nextState) {
  state = nextState;

  if (!environmentBuilt || !worldGroup) {
    buildWarehouseEnvironment();
  }

  updateNavigationVisuals();

  const rotationMap = {
    north: Math.PI,
    south: 0,
    east: Math.PI / 2,
    west: -Math.PI / 2
  };

  if (state.robots) {
    state.robots.forEach(r => {
      let entity = robotEntities.get(r.id);
      if (!entity) {
        const mesh = createRobotMesh(r.id);
        const initialPos = gridToWorld(r.row, r.col, 0);
        mesh.position.copy(initialPos);
        const rotY = rotationMap[r.orientation] || 0;
        mesh.rotation.y = rotY;

        entity = {
          group: mesh,
          currentPos: initialPos.clone(),
          targetPos: initialPos.clone(),
          currentRotY: rotY,
          targetRotY: rotY
        };
        robotEntities.set(r.id, entity);
      }

      const targetPos = gridToWorld(r.row, r.col, 0);
      entity.targetPos.copy(targetPos);
      entity.targetRotY = rotationMap[r.orientation] || 0;

      if (entity.group.userData.boxStackGroup) {
        entity.group.userData.boxStackGroup.visible = Boolean(r.carrying);
      }
    });
  }

  if (selectedRobotId) {
    const selEntity = robotEntities.get(selectedRobotId);
    if (selEntity) {
      selectionRing.position.set(selEntity.group.position.x, 0.022, selEntity.group.position.z);
      selectionRing.visible = true;
    }
  } else {
    selectionRing.visible = false;
  }

  renderSidebarPanels();
}

// ─────────────────────────────────────────────────────────────────────────────
// Sidebar Panels & UI Updates
// ─────────────────────────────────────────────────────────────────────────────

function renderSidebarPanels() {
  if (!state) return;

  const activeCount = state.robots ? state.robots.filter(r => r.status !== 'idle').length : 0;
  const totalCount = state.robots ? state.robots.length : 10;
  const fleetCountEl = document.getElementById('fleet-count');
  if (fleetCountEl) fleetCountEl.textContent = `${activeCount} / ${totalCount}`;

  const statusEl = document.getElementById('sim-status');
  if (statusEl) statusEl.textContent = state.running ? 'RUNNING' : 'PAUSED';

  const statusWrap = document.querySelector('.simulation-status');
  if (statusWrap) statusWrap.classList.toggle('running', Boolean(state.running));

  const tickEl = document.getElementById('sim-tick');
  if (tickEl) tickEl.textContent = state.tick ?? 0;

  const m = state.metrics || {};
  const metricMap = [
    ['sim-completed', m.completed ?? 0],
    ['sim-pending', m.pending ?? 0],
    ['sim-efficiency', `${m.efficiency ?? 0}%`],
    ['sim-utilization', `${m.utilization ?? 0}%`],
    ['sim-cycle', m.average_cycle ?? 0],
    ['sim-reservations', state.reservations ? state.reservations.length : 0]
  ];
  metricMap.forEach(([id, val]) => {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
  });

  const fleetListEl = document.getElementById('fleet-list');
  if (fleetListEl && state.robots) {
    fleetListEl.innerHTML = state.robots.map(r => `
      <div class="fleet-row ${selectedRobotId === r.id ? 'selected' : ''}" data-robot="${r.id}">
        <span class="state-dot ${r.carrying ? 'carrying' : r.status !== 'idle' ? '' : 'waiting'}"></span>
        <b class="fleet-id">${r.id}</b>
        <span class="fleet-state">${r.status.toUpperCase()} ${r.carrying ? '· 📦 CARGO' : ''}</span>
        <small style="color:var(--text-muted); font-size:0.6rem;">(${r.row}, ${r.col})</small>
      </div>
    `).join('');

    fleetListEl.querySelectorAll('.fleet-row').forEach(rowEl => {
      rowEl.onclick = () => selectRobotById(rowEl.dataset.robot);
    });
  }

  const eventsEl = document.getElementById('sim-events');
  if (eventsEl && state.events) {
    eventsEl.innerHTML = state.events.slice(0, 10).map(e => `
      <div class="event-item">T${e.tick} · ${e.message}</div>
    `).join('');
  }

  if (selectedRobotId && state.robots) {
    const selRobot = state.robots.find(r => r.id === selectedRobotId);
    showRobotDetails(selRobot);
  }
}

function showRobotDetails(robot) {
  const panel = document.getElementById('selected-robot');
  if (!panel) return;
  if (!robot) {
    panel.innerHTML = `<div class="panel-heading">Robot details</div><p>Click any robot in the 3D scene or fleet list.</p>`;
    return;
  }

  const remaining = robot.path ? Math.max(0, robot.path.length - robot.path_index) : 0;
  panel.innerHTML = `
    <div class="panel-heading">
      <span>Robot details</span>
      <b style="color:var(--neon-blue); font-size:0.8rem;">${robot.id}</b>
    </div>
    <div class="robot-detail">
      <strong>Status:</strong> ${robot.status.toUpperCase()}<br>
      <strong>Grid Pos:</strong> Row ${robot.row}, Col ${robot.col}<br>
      <strong>Order:</strong> ${robot.assigned_order || 'None (Idle)'}<br>
      <strong>Cargo:</strong> ${robot.carrying ? 'Yes (Box Stack Loaded)' : 'Empty / Available'}<br>
      <strong>Remaining Path:</strong> ${remaining} waypoints<br>
      <strong>Heading:</strong> ${robot.orientation.toUpperCase()}
    </div>
  `;
}

function showRackDetails(rackData) {
  const panel = document.getElementById('selected-rack');
  if (!panel) return;
  if (!rackData) {
    panel.innerHTML = `<div class="panel-heading">Storage Location</div><p>Click any storage rack in the 3D scene to inspect.</p>`;
    return;
  }

  panel.innerHTML = `
    <div class="panel-heading">
      <span>Storage Location</span>
      <b style="color:#ff8c35; font-size:0.8rem;">${rackData.id}</b>
    </div>
    <div class="rack-detail">
      <strong>Position:</strong> Row ${rackData.row}, Col ${rackData.col}<br>
      <strong>Levels:</strong> ${rackData.levels} Storage Tiers<br>
      <strong>Capacity:</strong> 12 Pallet Boxes<br>
      <strong>Status:</strong> Accessible from surrounding aisles<br>
      <strong>Obstacle:</strong> Active BFS Collision Boundary
    </div>
  `;
}

// ─────────────────────────────────────────────────────────────────────────────
// User Interaction & Raycasting
// ─────────────────────────────────────────────────────────────────────────────

function selectRobotById(id) {
  selectedRobotId = id;
  const selRobot = state?.robots?.find(r => r.id === id);
  showRobotDetails(selRobot);
  renderSidebarPanels();
}

function handleSceneClick(event) {
  if (!renderer || !camera) return;

  const rect = renderer.domElement.getBoundingClientRect();
  const mouse = new THREE.Vector2(
    ((event.clientX - rect.left) / rect.width) * 2 - 1,
    -((event.clientY - rect.top) / rect.height) * 2 + 1
  );

  raycaster.setFromCamera(mouse, camera);

  const robotHits = [];
  robotEntities.forEach(e => {
    if (e.group.userData.hitMesh) robotHits.push(e.group.userData.hitMesh);
  });

  const intersects = raycaster.intersectObjects(robotHits, false);
  if (intersects.length > 0) {
    const hitId = intersects[0].object.userData.robotId;
    if (hitId) {
      selectRobotById(hitId);
      return;
    }
  }

  const rackIntersects = raycaster.intersectObjects(rackMeshes, false);
  if (rackIntersects.length > 0) {
    const rData = rackIntersects[0].object.userData;
    if (rData && rData.isRack) {
      selectedRackData = rData;
      showRackDetails(rData);
      return;
    }
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Camera Controls (Isometric & Top View)
// ─────────────────────────────────────────────────────────────────────────────

function resetIsometricCamera() {
  if (!camera || !controls) return;
  camera.position.set(22, 25, 26);
  controls.target.set(0, 0, 0);
  controls.update();
}

function setTopDownCamera() {
  if (!camera || !controls) return;
  camera.position.set(0, 42, 0.001);
  controls.target.set(0, 0, 0);
  controls.update();
}

// ─────────────────────────────────────────────────────────────────────────────
// Animation Loop & Smooth Movement Interpolation
// ─────────────────────────────────────────────────────────────────────────────

function renderFrame() {
  robotEntities.forEach(entity => {
    entity.group.position.lerp(entity.targetPos, 0.15);

    let diff = entity.targetRotY - entity.group.rotation.y;
    while (diff < -Math.PI) diff += Math.PI * 2;
    while (diff > Math.PI) diff -= Math.PI * 2;
    entity.group.rotation.y += diff * 0.18;
  });

  if (selectionRing && selectionRing.visible) {
    const t = Date.now() * 0.004;
    const scale = 1.0 + Math.sin(t) * 0.06;
    selectionRing.scale.set(scale, scale, 1);
  }

  controls?.update();
  if (renderer && scene && camera) {
    renderer.render(scene, camera);
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// 2D Fallback Canvas (WebGL Unavailable)
// ─────────────────────────────────────────────────────────────────────────────

function initFallback2D() {
  if (fallbackCanvas) return;
  fallbackCanvas = document.createElement('canvas');
  fallbackCanvas.setAttribute('aria-label', '2D warehouse simulation fallback');
  root.appendChild(fallbackCanvas);
  hideWebGLError();
  handleResize();

  function fallbackLoop() {
    drawFallback2D();
    fallbackAnimationId = requestAnimationFrame(fallbackLoop);
  }
  fallbackLoop();
}

function drawFallback2D() {
  if (!fallbackCanvas) return;
  const ctx = fallbackCanvas.getContext('2d');
  const w = root.clientWidth || 800;
  const h = root.clientHeight || 650;
  fallbackCanvas.width = w * (window.devicePixelRatio || 1);
  fallbackCanvas.height = h * (window.devicePixelRatio || 1);
  ctx.setTransform(window.devicePixelRatio || 1, 0, 0, window.devicePixelRatio || 1, 0, 0);

  ctx.fillStyle = '#0a131f';
  ctx.fillRect(0, 0, w, h);

  const rows = state?.grid?.rows || DEFAULT_WAREHOUSE_CONFIG.grid.rows;
  const cols = state?.grid?.cols || DEFAULT_WAREHOUSE_CONFIG.grid.cols;

  const scale = Math.min((w - 80) / cols, (h - 80) / rows);
  const ox = (w - cols * scale) / 2;
  const oy = (h - rows * scale) / 2;

  ctx.strokeStyle = '#f5b300';
  ctx.lineWidth = 1;
  for (let c = 0; c <= cols; c++) {
    ctx.beginPath(); ctx.moveTo(ox + c * scale, oy); ctx.lineTo(ox + c * scale, oy + rows * scale); ctx.stroke();
  }
  for (let r = 0; r <= rows; r++) {
    ctx.beginPath(); ctx.moveTo(ox, oy + r * scale); ctx.lineTo(ox + cols * scale, oy + r * scale); ctx.stroke();
  }

  const shelves = state?.shelves || DEFAULT_WAREHOUSE_CONFIG.shelves;
  shelves.forEach(s => {
    const x = ox + s.col * scale;
    const y = oy + s.row * scale;
    ctx.fillStyle = '#165899';
    ctx.fillRect(x + 2, y + 2, scale - 4, scale - 4);
    ctx.fillStyle = '#eb5f12';
    ctx.fillRect(x + 2, y + 2, scale - 4, 3);
  });

  if (state?.robots) {
    state.robots.forEach(r => {
      const rx = ox + (r.col + 0.5) * scale;
      const ry = oy + (r.row + 0.5) * scale;
      ctx.fillStyle = '#ff6600';
      ctx.beginPath();
      ctx.arc(rx, ry, scale * 0.38, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = '#ffffff';
      ctx.font = 'bold 11px sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(r.id, rx, ry);
    });
  }
}

function handleResize() {
  const { width, height, aspect } = getSafeViewportDimensions();
  if (fallbackCanvas) {
    fallbackCanvas.width = width * (window.devicePixelRatio || 1);
    fallbackCanvas.height = height * (window.devicePixelRatio || 1);
  }
  if (!renderer || !camera) return;
  renderer.setSize(width, height);
  camera.aspect = aspect;
  camera.updateProjectionMatrix();
}

// ─────────────────────────────────────────────────────────────────────────────
// Backend API Communication
// ─────────────────────────────────────────────────────────────────────────────

async function fetchAPI(url, options = {}) {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...options
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

async function sendCommand(url, options = {}) {
  try {
    const nextState = await fetchAPI(url, options);
    applySimulationState(nextState);
  } catch (err) {
    console.error('[Warehouse 3D] Command failed:', url, err);
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Event Listeners & Control Hookups
// ─────────────────────────────────────────────────────────────────────────────

document.getElementById('sim-start')?.addEventListener('click', () => {
  sendCommand('/api/simulation/start', { method: 'POST' });
});

document.getElementById('sim-pause')?.addEventListener('click', () => {
  sendCommand('/api/simulation/pause', { method: 'POST' });
});

document.getElementById('sim-reset')?.addEventListener('click', async () => {
  selectedRobotId = null;
  selectedRackData = null;
  if (selectionRing) selectionRing.visible = false;
  robotEntities.forEach(e => robotGroup.remove(e.group));
  robotEntities.clear();
  await sendCommand('/api/simulation/reset', { method: 'POST' });
});

document.getElementById('sim-order')?.addEventListener('click', () => {
  sendCommand('/api/simulation/order', { method: 'POST' });
});

document.getElementById('sim-speed')?.addEventListener('change', e => {
  sendCommand('/api/simulation/speed', {
    method: 'POST',
    body: JSON.stringify({ speed: Number(e.target.value) })
  });
});

document.getElementById('sim-camera')?.addEventListener('click', resetIsometricCamera);
document.getElementById('sim-topview')?.addEventListener('click', setTopDownCamera);

document.getElementById('sim-paths')?.addEventListener('change', updateNavigationVisuals);
document.getElementById('sim-grid')?.addEventListener('change', e => {
  if (gridGroup) gridGroup.visible = e.target.checked;
});

// Global runtime error monitor to catch rendering failures and show error overlay
window.addEventListener('error', (event) => {
  if (event.filename && event.filename.includes('simulation3d')) {
    console.error('[Warehouse 3D Global Error]', event.error || event.message);
    const probe = probeWebGLSupport();
    showWebGLError(event.error || new Error(event.message), probe);
  }
});

// ─────────────────────────────────────────────────────────────────────────────
// Initialization Lifecycle
// ─────────────────────────────────────────────────────────────────────────────

function startSimulationApp() {
  if (isAppStarted) return;
  isAppStarted = true;

  try {
    const initialized = initThreeScene();
    if (!initialized) {
      console.warn('[Warehouse 3D] WebGL scene could not be initialized.');
      return;
    }

    // Build the 3D warehouse environment immediately so the viewport is never blank
    buildWarehouseEnvironment();

    // Fetch initial simulation state from backend
    fetchAPI('/api/simulation/state')
      .then(initialState => {
        applySimulationState(initialState);
      })
      .catch(err => {
        console.warn('[Warehouse 3D] Could not fetch initial state from backend:', err);
      });

    // Start background polling every 250ms
    setInterval(() => {
      fetchAPI('/api/simulation/state')
        .then(applySimulationState)
        .catch(err => {
          console.debug('[Warehouse 3D] State poll error:', err.message);
        });
    }, 250);

  } catch (err) {
    console.error('[Warehouse 3D] Fatal error in startSimulationApp:', err);
    const probe = probeWebGLSupport();
    showWebGLError(err, probe);
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', startSimulationApp);
} else {
  // Allow browser layout pass to settle dimensions before initializing
  requestAnimationFrame(startSimulationApp);
}
