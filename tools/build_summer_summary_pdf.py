from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "supervisor" / "2026暑假_AutoContract研究总结.pdf"
OUT.parent.mkdir(parents=True, exist_ok=True)

FONT = r"C:\Windows\Fonts\NotoSansSC-VF.ttf"
pdfmetrics.registerFont(TTFont("NotoSC", FONT))

styles = getSampleStyleSheet()
title = ParagraphStyle(
    "TitleCN", parent=styles["Title"], fontName="NotoSC", fontSize=20,
    leading=28, alignment=TA_CENTER, textColor=colors.HexColor("#17324D"),
    spaceAfter=7 * mm,
)
subtitle = ParagraphStyle(
    "SubtitleCN", parent=styles["Normal"], fontName="NotoSC", fontSize=10,
    leading=16, alignment=TA_CENTER, textColor=colors.HexColor("#667788"),
    spaceAfter=9 * mm,
)
heading = ParagraphStyle(
    "HeadingCN", parent=styles["Heading2"], fontName="NotoSC", fontSize=14,
    leading=21, textColor=colors.HexColor("#17324D"), spaceBefore=5 * mm,
    spaceAfter=2.5 * mm,
)
body = ParagraphStyle(
    "BodyCN", parent=styles["BodyText"], fontName="NotoSC", fontSize=10.5,
    leading=19, alignment=TA_LEFT, textColor=colors.HexColor("#222222"),
    wordWrap="CJK", firstLineIndent=2 * 10.5, spaceAfter=3.2 * mm,
)
bullet = ParagraphStyle(
    "BulletCN", parent=body, leftIndent=7 * mm, firstLineIndent=-4 * mm,
    bulletIndent=0, spaceAfter=2.2 * mm,
)
note = ParagraphStyle(
    "NoteCN", parent=body, fontSize=9.3, leading=16, textColor=colors.HexColor("#556270"),
    backColor=colors.HexColor("#F2F6F9"), borderColor=colors.HexColor("#D7E2EA"),
    borderWidth=0.5, borderPadding=4 * mm, firstLineIndent=0,
)


def P(text, style=body):
    return Paragraph(text, style)


def footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#D7E2EA"))
    canvas.line(18 * mm, 15 * mm, 192 * mm, 15 * mm)
    canvas.setFont("NotoSC", 8.5)
    canvas.setFillColor(colors.HexColor("#788896"))
    canvas.drawString(18 * mm, 9.5 * mm, "AutoContract 暑假研究总结")
    canvas.drawRightString(192 * mm, 9.5 * mm, f"第 {doc.page} 页")
    canvas.restoreState()


story = [
    P("AutoContract 暑假研究总结", title),
    P("给老师的阶段性汇报 · 2026 年暑假", subtitle),
    P("王阿姨您好，暑假差不多结束了，我想跟您汇报一下这段时间 AutoContract 课题的进展，还有我读完您之前发给我的论文后的一些想法。", body),
    P("也想先谢谢您一直对我的事情很上心。之前我刚开始讲这个想法时，其实自己也没有完全想清楚，您还是认真听了，还建议我先设计一个简单、可控制的实验来验证。后来您在出差路上也记着这件事，又专门把以前学生的毕业论文发给我参考。这些建议对我帮助很大，也让我没有一开始就把问题做得太大。", body),

    P("一、课题理解和最初的实验设计", heading),
    P("我目前研究的是机器学习数据预处理流水线的安全优化。像裁剪、缩放、归一化这些操作，如果只是为了提高速度就直接改变顺序，最后得到的数据可能会发生变化，进而影响模型训练。所以我把 AutoContract 设计成优化器前面的安全检查：先判断哪些操作可以调整，再让 Cedar 这类优化器决定具体怎么调整。", body),
    P("刚开始我先在 PyTorch 和 Cedar 上做了一个小型原型。实验不是一上来就测总训练时间，而是先检查 AutoContract 生成的限制条件有没有被 Cedar 真正使用。例如，加入某个操作依赖后，Cedar 的候选顺序是否减少；移除限制后，候选方案是否恢复。这样可以确认程序不是只生成了一份形式上的记录。", body),

    P("二、实验过程中发现的问题", heading),
    P("我一开始以为，确定性、没有内部状态的操作可能就可以交换。后来我用几个简单的数学操作做了反例，发现它们单独看都很安全，但改变顺序后输出仍然会不同。这个结果让我意识到，不能只根据操作是否随机、是否有状态来判断可交换性。", body),
    P("所以后面我把判断方式改成针对具体操作对进行验证，并把操作代码、参数、输入条件和随机数使用方式一起考虑。只有这些条件都符合时才允许重排，如果证据不够，就保持原来的顺序。之后我又用一些真实的图像处理操作测试，发现输入尺寸、数据类型和随机数分配都会影响结果，因此这部分不能简单地用一条通用规则解决。", body),

    KeepTogether([
        P("三、目前的实验结果", heading),
        P("性能实验采用先检查语义、再比较时间的顺序。也就是说，先确认重排前后的数据、随机状态和训练结果一致，再看运行时间。同时尽量固定运行环境、数据划分、随机种子和执行顺序，减少其他因素的影响。", body),
    ]),
    P("目前已经确认，AutoContract 生成的限制可以被 Cedar 实际消费，在允许重排的测试中，前后输出和训练结果也可以保持一致。不过性能提升还不稳定。在 DIV2K 高分辨率图片上的端到端实验没有达到预先设置的加速标准。后面测试的 8 种模型、输入尺寸和执行顺序组合中，有 7 种比对照组快，1 种略慢，但这些结果目前更适合用来观察哪些场景可能有效，还不能总结成整体加速。", body),
    P("这个结果对我来说也很重要，因为它说明能够安全重排，不代表重排以后一定更快。安全判断和性能判断需要分开，不能因为一个方案在语义上是正确的，就直接认为它在系统层面有收益。", note),

    P("四、阅读论文后的理解和收获", heading),
    P("您发来的论文主要研究基于近数据处理的深度学习数据加载方法。论文通过存储侧提前准备数据、主动推送、调整预处理顺序和动态分配任务，减少训练时等待数据的时间。它和 AutoContract 有一部分共同目标，都是优化深度学习数据预处理流水线，但解决问题的角度不一样。论文更关注怎样通过系统设计让数据加载更快，AutoContract 更关注改变流水线以后结果是否仍然正确。", body),
    P("论文中对我最有帮助的是实验设计。它不是只比较原始方案和最终方案，而是逐步加入数据预取、主动推送、存储侧预处理、顺序优化和动态卸载，分别观察每个部分的作用。另外，论文同时记录训练时间、数据加载占比、预处理吞吐量和 CPU 利用率，这让我认识到，性能实验不能只看一个总时间。", body),
    P("论文还使用数据膨胀因子来判断一个预处理操作会让数据变大还是变小。这个指标可以作为性能方面的参考，帮助判断怎样调整顺序可能更快。但它不能代替语义证明，因为数据量变小并不等于两个操作交换后一定得到相同结果。我的想法是，先由 AutoContract 划定安全的重排范围，再结合数据量、操作耗时和输入尺寸来选择真正值得执行的重排。", body),

    P("五、后续准备和想请教的问题", heading),
    P("接下来我想把实验设计得更清楚一些。除了比较原始方案和重排方案，还可以把安全检查、操作重排和成本选择分开做对照；除了总运行时间，也记录预处理时间和数据等待时间；正式比较时增加重复次数，报告结果的波动，而不是只看一次运行。", body),
    P("我想请教您两个问题：第一，后续应该先扩大真实图像处理操作的安全验证范围，还是先加入论文中的数据大小和操作耗时这些成本信息？第二，以我目前本科阶段的研究范围，是否可以先把 AutoContract 定位成流水线优化前的安全检查方法，不继续扩展到完整的近数据处理和动态卸载系统？", body),
    P("以上是我这个暑假的大概进展。目前有些地方还不成熟，性能方面也没有得到特别稳定的结果，所以我想先如实跟您汇报，再听听您的意见。也真的感谢您一直记着我的研究进展，还专门帮我找资料、给我建议。我会继续把这个课题认真做下去，有不清楚的地方再向您请教。", body),
]

doc = SimpleDocTemplate(
    str(OUT), pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm,
    topMargin=17 * mm, bottomMargin=21 * mm, title="AutoContract 暑假研究总结",
    author="AutoContract research",
)
doc.build(story, onFirstPage=footer, onLaterPages=footer)
print(OUT)
