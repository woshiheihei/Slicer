# Curve Curvature Visualization 模块说明

本模块用于在 3D Slicer 中对 Markups 曲线（vtkMRMLMarkupsCurveNode）进行逐点曲率相关要素的可视化，帮助理解和调试曲线几何计算流程。可视化内容与 Slicer 源码中 `vtkCurveMeasurementsCalculator::CalculatePolyDataCurvature` 的思路一致，展示以下要素：

- 控制点位置（白色小球）
- 邻接线段折线（灰色折线）
- 切向量 T（绿色箭头）
- 切向量变化量 ΔT（红色箭头）

模块会在场景中生成对应的 Model 节点，便于单独控制显示与样式。

## 功能概览

- 选择任意 Markups Curve 并一键生成可视化模型
- 可调节箭头长度（mm）与点球半径（mm）
- 提供主面板与“无模式”浮动面板两种操作界面
- 自动将生成的模型挂载到所选曲线的主题层级（Subject Hierarchy）下，方便管理
- 再次运行同一曲线的可视化时，会清理旧的同名前缀模型并重新生成
- 一键清除本模块创建的所有可视化节点

## 算法与可视化说明

假设曲线采样点为 P[i]（来自曲线的 world 坐标 PolyData 节点）。

1. 切向量 T[i]
	- 对开口曲线：T[i] = normalize(P[i+1] - P[i])，最后一个点沿用前一个切向量
	- 对闭合曲线：T[i] = normalize(P[(i+1) mod n] - P[i])
2. 切向量变化 ΔT[i]
	- 对开口曲线：ΔT[0] = 0；其余 ΔT[i] = T[i] - T[i-1]
	- 对闭合曲线：ΔT[i] = T[i] - T[(i-1) mod n]
3. 判断闭合：优先使用曲线节点的 `GetCurveClosed()`；若不可用或不可靠，则根据首末点距离近似判断闭合。

可视化产物：

- Points：以球体 glyph 标记各采样点（白色）
- Segments：按采样点顺序连线（灰色，线宽 2）
- Tangents：在每个点绘制切向量箭头（绿色，按向量长度缩放，并整体乘以“箭头长度”因子）
- DeltaT：在每个点绘制切向量变化量箭头（红色，按向量长度缩放，并整体乘以“箭头长度”因子）

注：开口曲线最后一点不绘制切向量，开口曲线第一个点的 ΔT 为零不绘制；闭合曲线则作环状处理。

## 使用方法

### 1) 主面板（模块 UI）

1. 在模块选择器中打开 “Curve Curvature Visualization”。
2. Curve node：选择一个已有的 Markups Curve。
3. Arrow length (mm)：设置箭头整体缩放因子（默认 5.0 mm）。
4. Point sphere radius (mm)：设置球体半径（默认 1.5 mm）。
5. 点击 “Start Visualization” 生成或更新可视化。
6. 点击 “Clear Visualization” 一键移除由本模块创建的节点。

状态信息会显示在面板底部的提示标签中。

### 2) 浮动面板（无模式对话框）

点击主面板中的 “Open Floating Panel (Modeless)” 打开浮动窗口，可在不阻塞操作的情况下反复调整参数并更新可视化。

在浮动面板中也提供同样的三个控件与两个按钮：

- Curve node、Arrow length、Point sphere radius
- Start Visualization、Clear Visualization

可以将浮动面板与 3D 视图并列使用以获得更流畅的调参体验。

## 生成的节点与命名

每次对某曲线运行可视化时，会以 `CurvViz_<CurveName>_XXX` 命名创建若干 Model 节点：

- `CurvViz_<CurveName>_Points`
- `CurvViz_<CurveName>_Segments`
- `CurvViz_<CurveName>_Tangents`
- `CurvViz_<CurveName>_DeltaT`

若再次对同一曲线运行，将先清理同名前缀的旧节点后再创建新节点。模块同时会尝试将这些节点归入该曲线所在的主题层级下，便于折叠管理。

## 注意事项与限制

- 需要曲线已有至少 2 个点；少于 2 点时不可视化。
- 对开口曲线，最后一点的 T 不定义（使用前一点近似）；ΔT 的首点为零。
- 若两个相邻点重合或极近，切向量长度可能为零，会导致该处箭头不可见。
- 箭头长度仅为可视化缩放，不代表物理量大小；请结合实际需求调整。
- 闭合性自动判定可能受数值误差影响；如需严格闭合，请确保曲线节点的闭合属性正确或首末点一致。

## 开发与测试

- 逻辑类：`CurveCurvatureVizLogic`
- 入口/界面：`CurveCurvatureViz` 与 `CurveCurvatureVizWidget`
- 浮动面板：`CurveCurvatureVizFloatingDialog`

模块包含一个简单的测试用例 `CurveCurvatureVizTest.test_basic`：

- 在空场景中新建一个半径约 30mm 的近似圆曲线（24 个点）
- 运行可视化并断言已创建至少三个模型节点
- 清理后断言创建列表为空

开发者可在 Slicer 的 Python 控制台或脚本环境中加载本模块文件进行调试。

## 故障排查

- 提示“Curve has no polydata”或“Need at least 2 curve points”：请先在曲线中添加足够的控制点。
- 箭头太短/太长：适当调整 Arrow length（mm）。
- 点太大/太小：调整 Point sphere radius（mm）。
- 生成节点过多：先点击 Clear Visualization 清理，或删除以 `CurvViz_` 开头的模型节点。

## 许可与致谢

- 模块基于 3D Slicer 平台与 VTK，可视化实现参考了 Slicer 源码中的曲率计算逻辑。
- 版权与许可以 Slicer 仓库中顶层的 License/COPYRIGHT 为准。

