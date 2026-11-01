// 用 ScreenCaptureKit 录制系统音频（含 iOS 模拟器输出）到 WAV。用法: swift sckaudio.swift out.wav 秒数
import Foundation
import ScreenCaptureKit
import AVFoundation
import CoreMedia

let args = CommandLine.arguments
let outURL = URL(fileURLWithPath: args.count > 1 ? args[1] : "out.wav")
let secs = Double(args.count > 2 ? args[2] : "10") ?? 10

final class Rec: NSObject, SCStreamOutput, SCStreamDelegate {
    var file: AVAudioFile?
    var frames: Int64 = 0
    var errs = 0
    var peak: Float = 0
    func stream(_ stream: SCStream, didOutputSampleBuffer sb: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .audio, sb.isValid else { return }
        guard let fd = CMSampleBufferGetFormatDescription(sb),
              let asbd = CMAudioFormatDescriptionGetStreamBasicDescription(fd) else { return }
        let fmt = AVAudioFormat(streamDescription: asbd)!
        let n = AVAudioFrameCount(CMSampleBufferGetNumSamples(sb))
        guard let pcm = AVAudioPCMBuffer(pcmFormat: fmt, frameCapacity: n) else { return }
        pcm.frameLength = n
        let st = CMSampleBufferCopyPCMDataIntoAudioBufferList(sb, at: 0, frameCount: Int32(n), into: pcm.mutableAudioBufferList)
        if st != noErr { errs += 1; if errs < 3 { FileHandle.standardError.write("copy err \(st)\n".data(using: .utf8)!) } }
        if let ch = pcm.floatChannelData { for i in 0..<Int(n) { peak = max(peak, abs(ch[0][i])) } }
        do {
            if file == nil { file = try AVAudioFile(forWriting: outURL, settings: fmt.settings, commonFormat: .pcmFormatFloat32, interleaved: false) }
            try file!.write(from: pcm); frames += Int64(n)
        } catch { FileHandle.standardError.write("write err \(error)\n".data(using: .utf8)!) }
    }
    func stream(_ stream: SCStream, didStopWithError error: Error) { print("stopped: \(error)"); exit(3) }
}

let rec = Rec()
Task {
    do {
        let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
        guard let display = content.displays.first else { print("no display"); exit(2) }
        let filter = SCContentFilter(display: display, excludingWindows: [])
        let cfg = SCStreamConfiguration()
        cfg.capturesAudio = true
        cfg.sampleRate = 48000
        cfg.channelCount = 2
        cfg.excludesCurrentProcessAudio = true
        cfg.width = 2; cfg.height = 2
        cfg.minimumFrameInterval = CMTime(value: 1, timescale: 1)
        let s = SCStream(filter: filter, configuration: cfg, delegate: rec)
        try s.addStreamOutput(rec, type: .audio, sampleHandlerQueue: DispatchQueue(label: "a"))
        try await s.startCapture()
        print("recording \(secs)s -> \(outURL.path)")
        try await Task.sleep(nanoseconds: UInt64(secs * 1e9))
        try await s.stopCapture()
        print("frames=\(rec.frames) peak=\(rec.peak) copyErrors=\(rec.errs)")
        exit(0)
    } catch { print("ERR \(error)"); exit(1) }
}
RunLoop.main.run()
