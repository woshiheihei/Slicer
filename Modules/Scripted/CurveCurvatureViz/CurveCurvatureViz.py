# -*- coding: utf-8 -*-

import os
import logging
import math
import time
import vtk, qt, ctk, slicer
from slicer.ScriptedLoadableModule import (
  ScriptedLoadableModule,
  ScriptedLoadableModuleWidget,
  ScriptedLoadableModuleLogic,
  ScriptedLoadableModuleTest,
)
from slicer.util import VTKObservationMixin

#
# CurveCurvatureViz
#

class CurveCurvatureViz(ScriptedLoadableModule):
  """ Scripted module wrapping. """
  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "Curve Curvature Visualization"
    self.parent.categories = ["Utilities"]
    self.parent.contributors = ["Your Name"]
    self.parent.helpText = (
      "Visualize per-point curvature steps (Points, Segments, Tangents, DeltaT) "
      "for a Markups Curve, following vtkCurveMeasurementsCalculator::CalculatePolyDataCurvature."
    )
    self.parent.acknowledgementText = ""
    iconPath = os.path.join(os.path.dirname(__file__), 'Resources', 'Icons', 'CurveCurvatureViz.png')
    if os.path.exists(iconPath):
      self.parent.icon = qt.QIcon(iconPath)


class CurveCurvatureVizWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
  def __init__(self, parent=None):
    ScriptedLoadableModuleWidget.__init__(self, parent)
    VTKObservationMixin.__init__(self)
    self.logic = None

  def setup(self):
    ScriptedLoadableModuleWidget.setup(self)
    self.logic = CurveCurvatureVizLogic()

    # Controls
    self.curveSelector = slicer.qMRMLNodeComboBox()
    self.curveSelector.nodeTypes = ["vtkMRMLMarkupsCurveNode"]
    self.curveSelector.setMRMLScene(slicer.mrmlScene)
    self.curveSelector.noneEnabled = False
    self.curveSelector.addEnabled = False
    self.curveSelector.removeEnabled = False

    self.arrowScaleSpin = qt.QDoubleSpinBox()
    self.arrowScaleSpin.decimals = 2
    self.arrowScaleSpin.minimum = 0.1
    self.arrowScaleSpin.maximum = 1000.0
    self.arrowScaleSpin.value = 5.0

    self.pointRadiusSpin = qt.QDoubleSpinBox()
    self.pointRadiusSpin.decimals = 2
    self.pointRadiusSpin.minimum = 0.1
    self.pointRadiusSpin.maximum = 50.0
    self.pointRadiusSpin.value = 1.5

    # Use Slicer torsion measurement pipeline
    self.enableTorsionCheck = qt.QCheckBox("Force enable torsion (Slicer pipeline)")
    self.enableTorsionCheck.checked = True

    form = qt.QFormLayout()
    form.addRow("Curve node:", self.curveSelector)
    form.addRow("Arrow length (mm):", self.arrowScaleSpin)
    form.addRow("Point sphere radius (mm):", self.pointRadiusSpin)
    form.addRow(self.enableTorsionCheck)

    self.startButton = qt.QPushButton("Start Visualization")
    self.clearButton = qt.QPushButton("Clear Visualization")
    self.floatingPanelButton = qt.QPushButton("Open Floating Panel (Modeless)")
    btnRow = qt.QHBoxLayout()
    btnRow.addWidget(self.startButton)
    btnRow.addWidget(self.clearButton)
    btnRow.addWidget(self.floatingPanelButton)

    self.statusLabel = qt.QLabel("")

    self.layout.addLayout(form)
    self.layout.addLayout(btnRow)
    self.layout.addWidget(self.statusLabel)

    self.startButton.clicked.connect(self.onStart)
    self.clearButton.clicked.connect(self.onClear)
    self.floatingPanelButton.clicked.connect(self.onOpenFloatingPanel)

  def onStart(self):
    curve = self.curveSelector.currentNode()
    if not curve:
      self.statusLabel.setText("Please select a curve node.")
      return
    try:
      self.logic.visualizeCurve(
        curve,
        arrowScaleMm=float(self.arrowScaleSpin.value),
        pointRadius=float(self.pointRadiusSpin.value),
        forceEnableTorsion=bool(self.enableTorsionCheck.isChecked()),
      )
      self.statusLabel.setText(f"Visualization updated for {curve.GetName()}.")
    except Exception as e:
      logging.exception(e)
      self.statusLabel.setText(f"Error: {e}")

  def onClear(self):
    self.logic.clear()
    self.statusLabel.setText("Cleared.")

  def onOpenFloatingPanel(self):
    dlg = CurveCurvatureVizFloatingDialog(self.logic, parent=slicer.util.mainWindow())
    dlg.setInitialState(curve=self.curveSelector.currentNode(), arrowLength=self.arrowScaleSpin.value, pointRadius=self.pointRadiusSpin.value)
    dlg.show(); dlg.raise_(); dlg.activateWindow()

class CurveCurvatureVizLogic(ScriptedLoadableModuleLogic):
  def __init__(self):
    ScriptedLoadableModuleLogic.__init__(self)
    self.createdNodes = []
    self.flightState = None

  def clear(self):
    for n in list(self.createdNodes):
      try:
        slicer.mrmlScene.RemoveNode(n)
      except Exception:
        pass
    self.createdNodes = []
    self.flightState = None

  def _isClosedFromPolyData(self, poly):
    try:
      pts = poly.GetPoints(); n = pts.GetNumberOfPoints()
      if n < 3:
        return False
      p0 = pts.GetPoint(0); pn = pts.GetPoint(n-1)
      d2 = (p0[0]-pn[0])**2 + (p0[1]-pn[1])**2 + (p0[2]-pn[2])**2
      return d2 < 1e-12
    except Exception:
      return False

  def visualizeCurve(self, curveNode, arrowScaleMm=5.0, pointRadius=1.5, forceEnableTorsion=False):
    curvePoly = curveNode.GetCurveWorld()
    if not curvePoly:
      raise RuntimeError('Curve has no polydata. Add control points first.')
    pts = curvePoly.GetPoints()
    if not pts or pts.GetNumberOfPoints() < 2:
      raise RuntimeError('Need at least 2 curve points for visualization.')
    n = pts.GetNumberOfPoints()
    closed = False
    if hasattr(curveNode, 'GetCurveClosed'):
      try:
        closed = bool(curveNode.GetCurveClosed())
      except Exception:
        closed = False
    if not closed:
      closed = self._isClosedFromPolyData(curvePoly)

    # Optionally enable torsion calculation in Slicer pipeline for exact parity
    torsionReady = False
    if forceEnableTorsion:
      try:
        torsionReady = bool(self._ensureTorsionComputed(curveNode))
        curvePoly = curveNode.GetCurveWorld()  # refresh after enabling
        pts = curvePoly.GetPoints(); n = pts.GetNumberOfPoints()
      except Exception:
        torsionReady = False

    P = [pts.GetPoint(i) for i in range(n)]

    # Prefer Slicer's internal arrays for exact pipeline parity
    pointData = curvePoly.GetPointData()
    def find_array(pd, candidates, comps=None):
      if not pd:
        return None
      nArr = pd.GetNumberOfArrays()
      for k in range(nArr):
        arr = pd.GetArray(k)
        if not arr:
          continue
        name = arr.GetName() or ""
        low = name.lower()
        for c in candidates:
          if low == c.lower() or c.lower() in low:
            if comps is not None and arr.GetNumberOfComponents() != comps:
              continue
            return arr
      return None

    tangentsArr = find_array(pointData, ["Tangents", "Tangent"], comps=3)
    normalsArr = find_array(pointData, ["Normals", "Normal"], comps=3)
    binormalsArr = find_array(pointData, ["Binormals", "Binormal", "BiNormals"], comps=3)
    torsionArr = find_array(pointData, ["Torsion"], comps=1) if (not forceEnableTorsion or torsionReady) else None

    # Assemble T from internal tangents if available; else fallback to simple finite difference
    T = []
    if tangentsArr:
      for i in range(n):
        T.append(tangentsArr.GetTuple3(i))
    else:
      for i in range(n):
        j = (i+1) % n
        if (not closed) and i == n-1:
          T.append(T[-1] if len(T)>0 else (0.0,0.0,0.0))
          continue
        d = (P[j][0]-P[i][0], P[j][1]-P[i][1], P[j][2]-P[i][2])
        l = math.sqrt(d[0]*d[0]+d[1]*d[1]+d[2]*d[2])
        T.append((d[0]/l, d[1]/l, d[2]/l) if l>0 else (0.0,0.0,0.0))

    # DeltaT from T (open: first is 0; closed: wrap)
    DT = []
    for i in range(n):
      if i==0 and not closed:
        DT.append((0.0,0.0,0.0))
        continue
      prev = T[n-1] if (i==0 and closed) else T[i-1]
      d = (T[i][0]-prev[0], T[i][1]-prev[1], T[i][2]-prev[2])
      DT.append(d)

    baseName = f"CurvViz_{curveNode.GetName()}"
    # Remove previous with same prefix
    for mdl in slicer.util.getNodesByClass('vtkMRMLModelNode'):
      if mdl.GetName().startswith(baseName):
        slicer.mrmlScene.RemoveNode(mdl)
        try:
          self.createdNodes.remove(mdl)
        except ValueError:
          pass

    # Points as spheres
    ptsPoly = vtk.vtkPolyData(); vpts = vtk.vtkPoints(); vpts.SetNumberOfPoints(n)
    for i,p in enumerate(P): vpts.SetPoint(i,p)
    verts = vtk.vtkCellArray()
    for i in range(n):
      verts.InsertNextCell(1); verts.InsertCellPoint(i)
    ptsPoly.SetPoints(vpts); ptsPoly.SetVerts(verts)
    sphere = vtk.vtkSphereSource(); sphere.SetRadius(pointRadius); sphere.SetPhiResolution(16); sphere.SetThetaResolution(16)
    gPoints = vtk.vtkGlyph3D(); gPoints.SetInputData(ptsPoly); gPoints.SetSourceConnection(sphere.GetOutputPort()); gPoints.ScalingOff(); gPoints.OrientOff(); gPoints.Update()
    pointsModel = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLModelNode', baseName+'_Points')
    pointsModel.CreateDefaultDisplayNodes(); pointsModel.GetDisplayNode().SetColor(1,1,1)
    polyOut = vtk.vtkPolyData(); polyOut.DeepCopy(gPoints.GetOutput()); pointsModel.SetAndObservePolyData(polyOut)
    self.createdNodes.append(pointsModel)

    # Segments polyline
    linesPoly = vtk.vtkPolyData(); linesPoly.SetPoints(vpts)
    lines = vtk.vtkCellArray()
    if closed:
      lines.InsertNextCell(n+1)
      for i in range(n): lines.InsertCellPoint(i)
      lines.InsertCellPoint(0)
    else:
      lines.InsertNextCell(n)
      for i in range(n): lines.InsertCellPoint(i)
    linesPoly.SetLines(lines)
    segModel = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLModelNode', baseName+'_Segments')
    segModel.CreateDefaultDisplayNodes(); segModel.GetDisplayNode().SetColor(0.6,0.6,0.6); segModel.GetDisplayNode().SetLineWidth(2.0)
    segOut = vtk.vtkPolyData(); segOut.DeepCopy(linesPoly); segModel.SetAndObservePolyData(segOut)
    self.createdNodes.append(segModel)

    # Vectors glyph helper
    def makeVectorsModel(name, anchors, vectors, color, scaleMm):
      pd = vtk.vtkPolyData(); aPts = vtk.vtkPoints(); aPts.SetNumberOfPoints(len(anchors))
      for i,p in enumerate(anchors): aPts.SetPoint(i,p)
      pd.SetPoints(aPts)
      vec = vtk.vtkDoubleArray(); vec.SetName('vectors'); vec.SetNumberOfComponents(3); vec.SetNumberOfTuples(len(vectors))
      for i,v in enumerate(vectors): vec.SetTuple3(i, v[0],v[1],v[2])
      pd.GetPointData().AddArray(vec); pd.GetPointData().SetActiveVectors('vectors')
      arrow = vtk.vtkArrowSource()
      glyph = vtk.vtkGlyph3D(); glyph.SetInputData(pd); glyph.SetSourceConnection(arrow.GetOutputPort())
      glyph.SetVectorModeToUseVector(); glyph.OrientOn(); glyph.SetScaleModeToScaleByVector(); glyph.SetScaleFactor(scaleMm); glyph.Update()
      model = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLModelNode', name)
      model.CreateDefaultDisplayNodes(); model.GetDisplayNode().SetColor(*color)
      gout = vtk.vtkPolyData(); gout.DeepCopy(glyph.GetOutput()); model.SetAndObservePolyData(gout)
      self.createdNodes.append(model)
      return model

    # Tangents (green)
    anchors_T = []; vecs_T = []
    for i in range(n):
      if (not closed) and i==n-1: continue
      anchors_T.append(P[i]); vecs_T.append(T[i])
    makeVectorsModel(baseName+'_Tangents', anchors_T, vecs_T, (0.0,0.9,0.2), arrowScaleMm)

    # DeltaT (red)
    anchors_DT = []; vecs_DT = []
    for i in range(n):
      if (not closed) and i==0: continue
      anchors_DT.append(P[i]); vecs_DT.append(DT[i])
    makeVectorsModel(baseName+'_DeltaT', anchors_DT, vecs_DT, (0.9,0.1,0.1), arrowScaleMm)

    # Normal unit vectors (yellow) if available
    if normalsArr:
      anchors_N = []; vecs_N = []
      for i in range(n):
        if (not closed) and i==n-1:
          continue
        v = normalsArr.GetTuple3(i)
        anchors_N.append(P[i]); vecs_N.append((v[0],v[1],v[2]))
      if len(vecs_N) > 0:
        makeVectorsModel(baseName+'_Normals', anchors_N, vecs_N, (0.95,0.75,0.10), arrowScaleMm)

    # Binormal unit vectors (magenta) if available
    if binormalsArr:
      anchors_B = []; vecs_B = []
      for i in range(n):
        if (not closed) and i==n-1:
          continue
        v = binormalsArr.GetTuple3(i)
        anchors_B.append(P[i]); vecs_B.append((v[0],v[1],v[2]))
      if len(vecs_B) > 0:
        makeVectorsModel(baseName+'_Binormals', anchors_B, vecs_B, (0.75,0.25,0.85), arrowScaleMm)

    # Torsion vectors from internal arrays: along Binormal scaled by Torsion (blue)
    if binormalsArr and torsionArr:
      anchors_tau = []; vecs_tau = []
      for i in range(n):
        b = binormalsArr.GetTuple3(i)
        tau = torsionArr.GetTuple1(i)
        anchors_tau.append(P[i])
        vecs_tau.append((b[0]*tau, b[1]*tau, b[2]*tau))
      if len(vecs_tau) > 0:
        makeVectorsModel(baseName+'_Torsion', anchors_tau, vecs_tau, (0.2,0.4,0.9), arrowScaleMm)

    # Parent SH under curve
    try:
      shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
      parentItem = shNode.GetItemByDataNode(curveNode)
      if parentItem:
        for n in self.createdNodes:
          shItem = shNode.GetItemByDataNode(n)
          if shItem:
            shNode.SetItemParent(shItem, parentItem)
    except Exception:
      pass

  def _ensureTorsionComputed(self, curveNode):
    # Preflight: need at least 3 points and 1 polyline
    try:
      poly = curveNode.GetCurveWorld()
      if not poly:
        return False
      if poly.GetNumberOfPoints() < 3 or poly.GetNumberOfLines() == 0:
        return False
    except Exception:
      return False

    # Try to enable torsion measurements on the node so the calculator computes torsion arrays
    # Prefer exact Slicer names first
    torsionNamesExact = ['torsion mean', 'torsion max']
    enabled = False
    for name in torsionNamesExact:
      try:
        m = curveNode.GetMeasurement(name)
      except Exception:
        m = None
      if m and hasattr(m, 'SetEnabled'):
        try:
          m.SetEnabled(True)
          enabled = True
        except Exception:
          pass
    # Fallback: any measurement containing 'torsion'
    if not enabled and hasattr(curveNode, 'GetMeasurements'):
      try:
        coll = curveNode.GetMeasurements()
        if coll and hasattr(coll, 'GetNumberOfItems'):
          for i in range(coll.GetNumberOfItems()):
            obj = coll.GetItemAsObject(i)
            if not obj:
              continue
            nm = obj.GetName() if hasattr(obj,'GetName') else ''
            if nm and ('torsion' in nm.lower()) and hasattr(obj,'SetEnabled'):
              try:
                obj.SetEnabled(True)
                enabled = True
              except Exception:
                continue
      except Exception:
        pass
    # Refresh polydata to allow pipeline to compute arrays
    try:
      _ = curveNode.GetCurveWorld()
    except Exception:
      pass
    return enabled

  # ------------------------ Aircraft Flight Animation ------------------------
  def _buildSimpleAircraftPolyData(self, scale=5.0):
    """Create a very simple aircraft-like arrow model as vtkPolyData.
    Forward direction is +X. Scale is overall length in mm."""
    # Body (cylinder along X)
    cyl = vtk.vtkCylinderSource()
    cyl.SetRadius(0.3)
    cyl.SetHeight(3.0)
    cyl.SetResolution(24)
    # Cylinder by default aligned with Z. We'll rotate to X using transform.
    tf1 = vtk.vtkTransform()
    tf1.RotateY(90)  # Z->X
    tfF1 = vtk.vtkTransformPolyDataFilter(); tfF1.SetInputConnection(cyl.GetOutputPort()); tfF1.SetTransform(tf1)

    # Nose (cone pointing +X)
    cone = vtk.vtkConeSource()
    cone.SetRadius(0.6)
    cone.SetHeight(1.2)
    cone.SetResolution(24)
    tf2 = vtk.vtkTransform(); tf2.RotateZ(90); tf2.Translate(2.1, 0.0, 0.0)  # Point to +X and move to front
    tfF2 = vtk.vtkTransformPolyDataFilter(); tfF2.SetInputConnection(cone.GetOutputPort()); tfF2.SetTransform(tf2)

    # Tail wing (flat box)
    tail = vtk.vtkCubeSource()
    tail.SetXLength(0.2); tail.SetYLength(1.8); tail.SetZLength(0.1)
    tf3 = vtk.vtkTransform(); tf3.Translate(-1.5, 0.0, 0.0)
    tfF3 = vtk.vtkTransformPolyDataFilter(); tfF3.SetInputConnection(tail.GetOutputPort()); tfF3.SetTransform(tf3)

    # Main wing (flat box)
    wing = vtk.vtkCubeSource()
    wing.SetXLength(0.3); wing.SetYLength(3.0); wing.SetZLength(0.12)
    tf4 = vtk.vtkTransform(); tf4.Translate(0.0, 0.0, 0.0)
    tfF4 = vtk.vtkTransformPolyDataFilter(); tfF4.SetInputConnection(wing.GetOutputPort()); tfF4.SetTransform(tf4)

    app = vtk.vtkAppendPolyData()
    app.AddInputConnection(tfF1.GetOutputPort())
    app.AddInputConnection(tfF2.GetOutputPort())
    app.AddInputConnection(tfF3.GetOutputPort())
    app.AddInputConnection(tfF4.GetOutputPort())
    app.Update()

    # Clean and scale
    clean = vtk.vtkCleanPolyData(); clean.SetInputConnection(app.GetOutputPort()); clean.Update()
    tfScale = vtk.vtkTransform(); tfScale.Scale(scale/4.0, scale/4.0, scale/4.0)
    tfFScale = vtk.vtkTransformPolyDataFilter(); tfFScale.SetInputConnection(clean.GetOutputPort()); tfFScale.SetTransform(tfScale); tfFScale.Update()
    out = vtk.vtkPolyData(); out.DeepCopy(tfFScale.GetOutput())
    return out

  def _extractCurveData(self, curveNode):
    """Return dict with positions P, cumulative distances S, totalLength, closed flag,
    and optional arrays for tangents, normals, binormals if available."""
    poly = curveNode.GetCurveWorld()
    if not poly or not poly.GetPoints() or poly.GetPoints().GetNumberOfPoints() < 2:
      raise RuntimeError('Curve must have at least 2 points.')
    pts = poly.GetPoints(); n = pts.GetNumberOfPoints()
    P = [pts.GetPoint(i) for i in range(n)]

    # Closed?
    closed = False
    if hasattr(curveNode, 'GetCurveClosed'):
      try:
        closed = bool(curveNode.GetCurveClosed())
      except Exception:
        closed = False
    if not closed:
      try:
        p0 = P[0]; pn = P[-1]
        d2 = (p0[0]-pn[0])**2 + (p0[1]-pn[1])**2 + (p0[2]-pn[2])**2
        closed = d2 < 1e-12
      except Exception:
        closed = False

    # Distances
    S = [0.0]
    total = 0.0
    segLens = []
    for i in range(n-1):
      d = math.dist(P[i], P[i+1])
      segLens.append(d)
      total += d
      S.append(total)
    if closed:
      # Add closing segment length
      d = math.dist(P[-1], P[0])
      total += d
    data = {'P': P, 'S': S, 'segLens': segLens, 'totalLength': total, 'closed': closed}

    # Internal arrays
    pd = poly.GetPointData()
    def find_array(pd, candidates, comps=None):
      if not pd:
        return None
      for k in range(pd.GetNumberOfArrays()):
        arr = pd.GetArray(k)
        if not arr:
          continue
        nm = (arr.GetName() or '').lower()
        for c in candidates:
          cl = c.lower()
          if nm == cl or cl in nm:
            if comps is not None and arr.GetNumberOfComponents() != comps:
              continue
            return arr
      return None
    data['tangentsArr'] = find_array(pd, ['Tangents','Tangent'], comps=3)
    data['normalsArr'] = find_array(pd, ['Normals','Normal'], comps=3)
    data['binormalsArr'] = find_array(pd, ['Binormals','Binormal','BiNormals'], comps=3)
    return data

  def _interpFrame(self, data, s):
    """Interpolate position and frame at arc-length s. Returns (pos, T, N, B)."""
    P = data['P']; S = data['S']; segLens = data['segLens']; n = len(P)
    closed = data['closed']; total = data['totalLength']
    if total <= 0:
      return (P[0], (1,0,0), (0,1,0), (0,0,1))
    # Wrap for closed
    if closed:
      s = s % total
    else:
      s = max(0.0, min(s, total))
    # Find segment
    if s <= 0: i = 0; t = 0.0
    elif s >= total and not closed:
      i = len(S)-2; t = 1.0
    else:
      # binary search
      lo, hi = 0, len(S)-1
      while lo < hi:
        mid = (lo+hi)//2
        if S[mid] <= s:
          lo = mid+1
        else:
          hi = mid
      i = max(0, lo-1)
      segLen = segLens[i] if i < len(segLens) else (math.dist(P[-1], P[0]) if closed else 1.0)
      ds = s - S[i]
      t = 0.0 if segLen == 0 else max(0.0, min(1.0, ds/segLen))
    j = (i+1) % n
    # Position
    pos = (
      P[i][0] + t*(P[j][0]-P[i][0]),
      P[i][1] + t*(P[j][1]-P[i][1]),
      P[i][2] + t*(P[j][2]-P[i][2]),
    )
    # Tangent
    def getVec(arr, idx):
      return arr.GetTuple3(idx) if arr else None
    Ti = getVec(data.get('tangentsArr'), i)
    Tj = getVec(data.get('tangentsArr'), j)
    if Ti and Tj:
      T = (Ti[0]*(1-t)+Tj[0]*t, Ti[1]*(1-t)+Tj[1]*t, Ti[2]*(1-t)+Tj[2]*t)
    else:
      # fallback finite difference
      d = (P[j][0]-P[i][0], P[j][1]-P[i][1], P[j][2]-P[i][2])
      T = d
    # Normalize T
    tl = math.sqrt(T[0]*T[0]+T[1]*T[1]+T[2]*T[2])
    if tl > 0:
      T = (T[0]/tl, T[1]/tl, T[2]/tl)
    else:
      T = (1,0,0)
    # Normal/binormal
    Ni = getVec(data.get('normalsArr'), i)
    Nj = getVec(data.get('normalsArr'), j)
    Bi = getVec(data.get('binormalsArr'), i)
    Bj = getVec(data.get('binormalsArr'), j)
    if Ni and Nj and Bi and Bj:
      N = (Ni[0]*(1-t)+Nj[0]*t, Ni[1]*(1-t)+Nj[1]*t, Ni[2]*(1-t)+Nj[2]*t)
      B = (Bi[0]*(1-t)+Bj[0]*t, Bi[1]*(1-t)+Bj[1]*t, Bi[2]*(1-t)+Bj[2]*t)
      # Orthonormalize
      # B = normalize(T x N); N = B x T
      # First normalize N
      nl = math.sqrt(N[0]*N[0]+N[1]*N[1]+N[2]*N[2])
      if nl > 0: N = (N[0]/nl, N[1]/nl, N[2]/nl)
      # B from T x N
      B = (T[1]*N[2]-T[2]*N[1], T[2]*N[0]-T[0]*N[2], T[0]*N[1]-T[1]*N[0])
      bl = math.sqrt(B[0]*B[0]+B[1]*B[1]+B[2]*B[2])
      if bl > 0: B = (B[0]/bl, B[1]/bl, B[2]/bl)
      # Recompute N to ensure orthogonality
      N = (B[1]*T[2]-B[2]*T[1], B[2]*T[0]-B[0]*T[2], B[0]*T[1]-B[1]*T[0])
    else:
      # Build a stable frame from a world up vector
      up = (0,0,1)
      dp = abs(T[0]*up[0] + T[1]*up[1] + T[2]*up[2])
      if dp > 0.95:
        up = (1,0,0)
      # N = normalize(up x T)
      N = (up[1]*T[2]-up[2]*T[1], up[2]*T[0]-up[0]*T[2], up[0]*T[1]-up[1]*T[0])
      nl = math.sqrt(N[0]*N[0]+N[1]*N[1]+N[2]*N[2])
      if nl > 0: N = (N[0]/nl, N[1]/nl, N[2]/nl)
      else: N = (0,1,0)
      B = (T[1]*N[2]-T[2]*N[1], T[2]*N[0]-T[0]*N[2], T[0]*N[1]-T[1]*N[0])
    return (pos, T, N, B)

  def _frameToMatrix4x4(self, pos, T, N, B):
    """Create vtkMatrix4x4 from frame columns X=T, Y=N, Z=B and origin pos."""
    m = vtk.vtkMatrix4x4()
    m.Identity()
    # Columns are basis vectors
    m.SetElement(0,0, T[0]); m.SetElement(1,0, T[1]); m.SetElement(2,0, T[2])  # X
    m.SetElement(0,1, N[0]); m.SetElement(1,1, N[1]); m.SetElement(2,1, N[2])  # Y
    m.SetElement(0,2, B[0]); m.SetElement(1,2, B[1]); m.SetElement(2,2, B[2])  # Z
    m.SetElement(0,3, pos[0]); m.SetElement(1,3, pos[1]); m.SetElement(2,3, pos[2])
    return m

  def setupAircraftFlight(self, curveNode, modelScaleMm=8.0, color=(0.2,0.6,1.0)):
    """Prepare aircraft model and transform for animation along the given curve."""
    data = self._extractCurveData(curveNode)
    # Create transform
    tnode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLLinearTransformNode', f"CurvViz_{curveNode.GetName()}_AircraftXform")
    # Create model
    model = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLModelNode', f"CurvViz_{curveNode.GetName()}_Aircraft")
    model.CreateDefaultDisplayNodes(); model.GetDisplayNode().SetColor(*color); model.GetDisplayNode().BackfaceCullingOff()
    model.SetAndObservePolyData(self._buildSimpleAircraftPolyData(scale=modelScaleMm))
    model.SetAndObserveTransformNodeID(tnode.GetID())
    self.createdNodes.extend([tnode, model])
    # Parent under curve
    try:
      shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
      parentItem = shNode.GetItemByDataNode(curveNode)
      for n in (tnode, model):
        shItem = shNode.GetItemByDataNode(n)
        if parentItem and shItem:
          shNode.SetItemParent(shItem, parentItem)
    except Exception:
      pass
    # Initial placement at start
    pos, T, N, B = self._interpFrame(data, 0.0)
    m = self._frameToMatrix4x4(pos, T, N, B)
    tnode.SetMatrixTransformToParent(m)
    self.flightState = {
      'curveNode': curveNode,
      'data': data,
      'transformNode': tnode,
      'modelNode': model,
      'distance': 0.0,
    }
    return self.flightState

  def removeAircraftFlight(self):
    if self.flightState:
      for key in ('modelNode','transformNode'):
        n = self.flightState.get(key)
        if n and n in self.createdNodes:
          try:
            slicer.mrmlScene.RemoveNode(n)
          except Exception:
            pass
          try:
            self.createdNodes.remove(n)
          except ValueError:
            pass
      self.flightState = None

  def updateAircraftAtDistance(self, s):
    if not self.flightState:
      return False
    data = self.flightState['data']
    pos, T, N, B = self._interpFrame(data, s)
    m = self._frameToMatrix4x4(pos, T, N, B)
    self.flightState['transformNode'].SetMatrixTransformToParent(m)
    self.flightState['distance'] = s
    return True

  def getFlightTotalLength(self):
    if not self.flightState:
      return 0.0
    return float(self.flightState['data']['totalLength'])


class CurveCurvatureVizFloatingDialog(qt.QDialog):
  def __init__(self, logic, parent=None):
    super().__init__(parent)
    self.setWindowTitle('Curve Curvature Visualization')
    self.setModal(False)
    self.setWindowModality(qt.Qt.NonModal)
    self.setMinimumWidth(420)
    self.logic = logic

    # Timer for animation
    self._timer = qt.QTimer(self)
    self._timer.setInterval(33)  # ~30 FPS
    self._timer.timeout.connect(self._onTick)
    self._lastTickTime = None

    # UI layout
    layout = qt.QVBoxLayout(self)
    self.curveSelector = slicer.qMRMLNodeComboBox()
    self.curveSelector.nodeTypes = ["vtkMRMLMarkupsCurveNode"]
    self.curveSelector.setMRMLScene(slicer.mrmlScene)
    self.curveSelector.noneEnabled = False
    self.curveSelector.addEnabled = False
    self.curveSelector.removeEnabled = False
    self.arrowScaleSpin = qt.QDoubleSpinBox(); self.arrowScaleSpin.decimals=2; self.arrowScaleSpin.minimum=0.1; self.arrowScaleSpin.maximum=1000.0; self.arrowScaleSpin.value=5.0
    self.pointRadiusSpin = qt.QDoubleSpinBox(); self.pointRadiusSpin.decimals=2; self.pointRadiusSpin.minimum=0.1; self.pointRadiusSpin.maximum=50.0; self.pointRadiusSpin.value=1.5
    self.enableTorsionCheck = qt.QCheckBox("Force enable torsion (Slicer pipeline)")
    self.enableTorsionCheck.checked = True

    form = qt.QFormLayout()
    form.addRow("Curve node:", self.curveSelector)
    form.addRow("Arrow length (mm):", self.arrowScaleSpin)
    form.addRow("Point sphere radius (mm):", self.pointRadiusSpin)
    form.addRow(self.enableTorsionCheck)
    layout.addLayout(form)

    row = qt.QHBoxLayout()
    self.startButton = qt.QPushButton("Start Visualization")
    self.clearButton = qt.QPushButton("Clear Visualization")
    row.addWidget(self.startButton); row.addWidget(self.clearButton)
    layout.addLayout(row)
    self.statusLabel = qt.QLabel("")
    layout.addWidget(self.statusLabel)

    # Aircraft Flight Animation group
    self.flightGroup = qt.QGroupBox('Aircraft Flight Animation')
    fl = qt.QVBoxLayout(self.flightGroup)
    # Controls row
    row2 = qt.QHBoxLayout()
    self.playBtn = qt.QPushButton('▶ Play'); self.playBtn.setToolTip('Start or resume animation')
    self.pauseBtn = qt.QPushButton('⏸ Pause'); self.pauseBtn.setToolTip('Pause animation')
    self.stopBtn = qt.QPushButton('⏹ Stop'); self.stopBtn.setToolTip('Stop and reset to start')
    row2.addWidget(self.playBtn); row2.addWidget(self.pauseBtn); row2.addWidget(self.stopBtn)
    fl.addLayout(row2)
    # Speed slider
    spRow = qt.QHBoxLayout()
    spRow.addWidget(qt.QLabel('Speed'))
    self.speedSlider = qt.QSlider(qt.Qt.Horizontal)
    self.speedSlider.setMinimum(1); self.speedSlider.setMaximum(50); self.speedSlider.setValue(10)
    self.speedSlider.setToolTip('Flight speed (mm/s)')
    self.speedValueLabel = qt.QLabel('10 mm/s')
    spRow.addWidget(self.speedSlider, 1)
    spRow.addWidget(self.speedValueLabel)
    fl.addLayout(spRow)
    layout.addWidget(self.flightGroup)

    # Connections
    self.startButton.clicked.connect(self.onStart)
    self.clearButton.clicked.connect(self.onClear)
    self.playBtn.clicked.connect(self.onPlay)
    self.pauseBtn.clicked.connect(self.onPause)
    self.stopBtn.clicked.connect(self.onStop)
    self.speedSlider.valueChanged.connect(self._onSpeedChanged)

  def setInitialState(self, curve=None, arrowLength=None, pointRadius=None):
    if curve:
      self.curveSelector.setCurrentNode(curve)
    if arrowLength is not None:
      self.arrowScaleSpin.value = float(arrowLength)
    if pointRadius is not None:
      self.pointRadiusSpin.value = float(pointRadius)
    self._onSpeedChanged()

  def onStart(self):
    curve = self.curveSelector.currentNode()
    if not curve:
      self.statusLabel.setText("Please select a curve node.")
      return
    try:
      self.logic.visualizeCurve(
        curve,
        arrowScaleMm=float(self.arrowScaleSpin.value),
        pointRadius=float(self.pointRadiusSpin.value),
        forceEnableTorsion=bool(self.enableTorsionCheck.isChecked()),
      )
      self.statusLabel.setText(f"Visualization updated for {curve.GetName()}.")
    except Exception as e:
      logging.exception(e)
      self.statusLabel.setText(f"Error: {e}")

  def onClear(self):
    self.logic.clear()
    self.statusLabel.setText("Cleared.")
    self._timer.stop(); self._lastTickTime = None

  # ---------------- Flight controls ----------------
  def _onSpeedChanged(self):
    self.speedValueLabel.setText(f"{int(self.speedSlider.value)} mm/s")

  def onPlay(self):
    curve = self.curveSelector.currentNode()
    if not curve:
      self.statusLabel.setText('Select a curve to animate.')
      return
    # If not set up or different curve, (re)setup
    if (not self.logic.flightState) or (self.logic.flightState.get('curveNode') != curve):
      try:
        self.logic.setupAircraftFlight(curve)
      except Exception as e:
        logging.exception(e)
        self.statusLabel.setText(f"Setup error: {e}")
        return
    # Start/resume
    self._lastTickTime = time.perf_counter()
    self._timer.start()
    self.statusLabel.setText('Playing…')

  def onPause(self):
    if self._timer.isActive():
      self._timer.stop()
      self.statusLabel.setText('Paused')

  def onStop(self):
    self._timer.stop(); self._lastTickTime = None
    if self.logic.flightState:
      try:
        self.logic.updateAircraftAtDistance(0.0)
        self.logic.flightState['distance'] = 0.0
      except Exception:
        pass
    self.statusLabel.setText('Stopped')

  def _onTick(self):
    if not self.logic.flightState:
      # No state; stop timer
      self._timer.stop(); self._lastTickTime = None
      return
    now = time.perf_counter()
    if self._lastTickTime is None:
      self._lastTickTime = now
      return
    dt = now - self._lastTickTime
    self._lastTickTime = now
    speed = float(int(self.speedSlider.value))  # mm/s
    s = self.logic.flightState.get('distance', 0.0) + speed * dt
    total = self.logic.getFlightTotalLength()
    if total <= 0:
      return
    closed = bool(self.logic.flightState['data']['closed'])
    if not closed and s >= total:
      # Clamp and stop
      s = total
      self.logic.updateAircraftAtDistance(s)
      self._timer.stop(); self._lastTickTime = None
      self.statusLabel.setText('Reached end')
      return
    # Update position (wrap if closed handled internally)
    self.logic.updateAircraftAtDistance(s)

class CurveCurvatureVizTest(ScriptedLoadableModuleTest):
  def runTest(self):
    self.setUp()
    self.test_basic()

  def setUp(self):
    slicer.mrmlScene.Clear(0)

  def test_basic(self):
    logic = CurveCurvatureVizLogic()
    curve = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLMarkupsCurveNode', 'TestCurve')
    r=30.0
    for k in range(24):
      ang = 2*math.pi*k/24.0
      curve.AddControlPointWorld(vtk.vtkVector3d(r*math.cos(ang), r*math.sin(ang), 0.0))
    logic.visualizeCurve(curve)
    self.assertTrue(len(logic.createdNodes) >= 3)
    logic.clear()
    self.assertTrue(len(logic.createdNodes) == 0)
