# -*- coding: utf-8 -*-

import os
import logging
import math
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

    form = qt.QFormLayout()
    form.addRow("Curve node:", self.curveSelector)
    form.addRow("Arrow length (mm):", self.arrowScaleSpin)
    form.addRow("Point sphere radius (mm):", self.pointRadiusSpin)

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
      self.logic.visualizeCurve(curve, arrowScaleMm=float(self.arrowScaleSpin.value), pointRadius=float(self.pointRadiusSpin.value))
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

  def clear(self):
    for n in list(self.createdNodes):
      try:
        slicer.mrmlScene.RemoveNode(n)
      except Exception:
        pass
    self.createdNodes = []

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

  def visualizeCurve(self, curveNode, arrowScaleMm=5.0, pointRadius=1.5):
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

    P = [pts.GetPoint(i) for i in range(n)]

    # Tangents Ti = normalize(P[i+1]-P[i]) (open: last reuses previous; closed: wrap)
    T = []
    segLen = []
    for i in range(n):
      j = (i+1) % n
      if (not closed) and i == n-1:
        T.append(T[-1] if len(T)>0 else (0.0,0.0,0.0))
        segLen.append(0.0)
        continue
      d = (P[j][0]-P[i][0], P[j][1]-P[i][1], P[j][2]-P[i][2])
      l = math.sqrt(d[0]*d[0]+d[1]*d[1]+d[2]*d[2])
      if l>0:
        T.append((d[0]/l, d[1]/l, d[2]/l))
      else:
        T.append((0.0,0.0,0.0))
      segLen.append(l)

    # DeltaT[i] = T[i]-T[i-1] (open: first is 0; closed: wrap)
    DT = []
    for i in range(n):
      if i==0:
        if closed:
          prev = T[n-1]
        else:
          DT.append((0.0,0.0,0.0)); continue
      else:
        prev = T[i-1]
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


class CurveCurvatureVizFloatingDialog(qt.QDialog):
  def __init__(self, logic, parent=None):
    super().__init__(parent)
    self.setWindowTitle('Curve Curvature Visualization')
    self.setModal(False)
    self.setWindowModality(qt.Qt.NonModal)
    self.setMinimumWidth(420)
    self.logic = logic

    layout = qt.QVBoxLayout(self)
    self.curveSelector = slicer.qMRMLNodeComboBox()
    self.curveSelector.nodeTypes = ["vtkMRMLMarkupsCurveNode"]
    self.curveSelector.setMRMLScene(slicer.mrmlScene)
    self.curveSelector.noneEnabled = False
    self.curveSelector.addEnabled = False
    self.curveSelector.removeEnabled = False
    self.arrowScaleSpin = qt.QDoubleSpinBox(); self.arrowScaleSpin.decimals=2; self.arrowScaleSpin.minimum=0.1; self.arrowScaleSpin.maximum=1000.0; self.arrowScaleSpin.value=5.0
    self.pointRadiusSpin = qt.QDoubleSpinBox(); self.pointRadiusSpin.decimals=2; self.pointRadiusSpin.minimum=0.1; self.pointRadiusSpin.maximum=50.0; self.pointRadiusSpin.value=1.5

    form = qt.QFormLayout()
    form.addRow("Curve node:", self.curveSelector)
    form.addRow("Arrow length (mm):", self.arrowScaleSpin)
    form.addRow("Point sphere radius (mm):", self.pointRadiusSpin)
    layout.addLayout(form)

    row = qt.QHBoxLayout()
    self.startButton = qt.QPushButton("Start Visualization")
    self.clearButton = qt.QPushButton("Clear Visualization")
    row.addWidget(self.startButton); row.addWidget(self.clearButton)
    layout.addLayout(row)
    self.statusLabel = qt.QLabel("")
    layout.addWidget(self.statusLabel)

    self.startButton.clicked.connect(self.onStart)
    self.clearButton.clicked.connect(self.onClear)

  def setInitialState(self, curve=None, arrowLength=None, pointRadius=None):
    if curve:
      self.curveSelector.setCurrentNode(curve)
    if arrowLength is not None:
      self.arrowScaleSpin.value = float(arrowLength)
    if pointRadius is not None:
      self.pointRadiusSpin.value = float(pointRadius)

  def onStart(self):
    curve = self.curveSelector.currentNode()
    if not curve:
      self.statusLabel.setText("Please select a curve node.")
      return
    try:
      self.logic.visualizeCurve(curve, arrowScaleMm=float(self.arrowScaleSpin.value), pointRadius=float(self.pointRadiusSpin.value))
      self.statusLabel.setText(f"Visualization updated for {curve.GetName()}.")
    except Exception as e:
      logging.exception(e)
      self.statusLabel.setText(f"Error: {e}")

  def onClear(self):
    self.logic.clear()
    self.statusLabel.setText("Cleared.")


    class CurveCurvatureVizLogic(ScriptedLoadableModuleLogic):
      def __init__(self):
        ScriptedLoadableModuleLogic.__init__(self)
        self.createdNodes = []

      def clear(self):
        for n in list(self.createdNodes):
          try:
            slicer.mrmlScene.RemoveNode(n)
          except Exception:
            pass
        self.createdNodes = []

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

      def visualizeCurve(self, curveNode, arrowScaleMm=5.0, pointRadius=1.5):
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

        P = [pts.GetPoint(i) for i in range(n)]

        # Tangents Ti = normalize(P[i+1]-P[i]) (open: last reuses previous; closed: wrap)
        T = []
        segLen = []
        for i in range(n):
          j = (i+1) % n
          if (not closed) and i == n-1:
            T.append(T[-1] if len(T)>0 else (0.0,0.0,0.0))
            segLen.append(0.0)
            continue
          d = (P[j][0]-P[i][0], P[j][1]-P[i][1], P[j][2]-P[i][2])
          l = math.sqrt(d[0]*d[0]+d[1]*d[1]+d[2]*d[2])
          if l>0:
            T.append((d[0]/l, d[1]/l, d[2]/l))
          else:
            T.append((0.0,0.0,0.0))
          segLen.append(l)

        # DeltaT[i] = T[i]-T[i-1] (open: first is 0; closed: wrap)
        DT = []
        for i in range(n):
          if i==0:
            if closed:
              prev = T[n-1]
            else:
              DT.append((0.0,0.0,0.0)); continue
          else:
            prev = T[i-1]
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


    class CurveCurvatureVizFloatingDialog(qt.QDialog):
      def __init__(self, logic, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Curve Curvature Visualization')
        self.setModal(False)
        self.setWindowModality(qt.Qt.NonModal)
        self.setMinimumWidth(420)
        self.logic = logic

        layout = qt.QVBoxLayout(self)
        self.curveSelector = slicer.qMRMLNodeComboBox()
        self.curveSelector.nodeTypes = ["vtkMRMLMarkupsCurveNode"]
        self.curveSelector.setMRMLScene(slicer.mrmlScene)
        self.curveSelector.noneEnabled = False
        self.curveSelector.addEnabled = False
        self.curveSelector.removeEnabled = False
        self.arrowScaleSpin = qt.QDoubleSpinBox(); self.arrowScaleSpin.decimals=2; self.arrowScaleSpin.minimum=0.1; self.arrowScaleSpin.maximum=1000.0; self.arrowScaleSpin.value=5.0
        self.pointRadiusSpin = qt.QDoubleSpinBox(); self.pointRadiusSpin.decimals=2; self.pointRadiusSpin.minimum=0.1; self.pointRadiusSpin.maximum=50.0; self.pointRadiusSpin.value=1.5

        form = qt.QFormLayout()
        form.addRow("Curve node:", self.curveSelector)
        form.addRow("Arrow length (mm):", self.arrowScaleSpin)
        form.addRow("Point sphere radius (mm):", self.pointRadiusSpin)
        layout.addLayout(form)

        row = qt.QHBoxLayout()
        self.startButton = qt.QPushButton("Start Visualization")
        self.clearButton = qt.QPushButton("Clear Visualization")
        row.addWidget(self.startButton); row.addWidget(self.clearButton)
        layout.addLayout(row)
        self.statusLabel = qt.QLabel("")
        layout.addWidget(self.statusLabel)

        self.startButton.clicked.connect(self.onStart)
        self.clearButton.clicked.connect(self.onClear)

      def setInitialState(self, curve=None, arrowLength=None, pointRadius=None):
        if curve:
          self.curveSelector.setCurrentNode(curve)
        if arrowLength is not None:
          self.arrowScaleSpin.value = float(arrowLength)
        if pointRadius is not None:
          self.pointRadiusSpin.value = float(pointRadius)

      def onStart(self):
        curve = self.curveSelector.currentNode()
        if not curve:
          self.statusLabel.setText("Please select a curve node.")
          return
        try:
          self.logic.visualizeCurve(curve, arrowScaleMm=float(self.arrowScaleSpin.value), pointRadius=float(self.pointRadiusSpin.value))
          self.statusLabel.setText(f"Visualization updated for {curve.GetName()}.")
        except Exception as e:
          logging.exception(e)
          self.statusLabel.setText(f"Error: {e}")

      def onClear(self):
        self.logic.clear()
        self.statusLabel.setText("Cleared.")


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
