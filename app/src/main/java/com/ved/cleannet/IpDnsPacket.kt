package com.ved.cleannet

/**
 * Minimal IPv4 / UDP helpers and DNS QNAME parsing for [DnsVpnService].
 */
internal object IpDnsPacket {

    fun ipv4HeaderLength(packet: ByteArray): Int = (packet[0].toInt() and 0x0F) * 4

    fun isIpv4(packet: ByteArray, len: Int): Boolean =
        len >= 20 && (packet[0].toInt() ushr 4) == 4

    fun ipProtocol(packet: ByteArray): Int = packet[9].toInt() and 0xFF

    fun ipTotalLength(packet: ByteArray): Int =
        ((packet[2].toInt() and 0xFF) shl 8) or (packet[3].toInt() and 0xFF)

    fun ipSrcDst(packet: ByteArray): Pair<ByteArray, ByteArray> {
        val s = packet.copyOfRange(12, 16)
        val d = packet.copyOfRange(16, 20)
        return s to d
    }

    fun udpPorts(packet: ByteArray, ipHdrLen: Int): Pair<Int, Int> {
        val o = ipHdrLen
        val src = ((packet[o].toInt() and 0xFF) shl 8) or (packet[o + 1].toInt() and 0xFF)
        val dst = ((packet[o + 2].toInt() and 0xFF) shl 8) or (packet[o + 3].toInt() and 0xFF)
        return src to dst
    }

    fun udpLength(packet: ByteArray, ipHdrLen: Int): Int =
        ((packet[ipHdrLen + 4].toInt() and 0xFF) shl 8) or (packet[ipHdrLen + 5].toInt() and 0xFF)

    fun udpPayloadOffset(ipHdrLen: Int): Int = ipHdrLen + 8

    fun dnsQueryHostname(dns: ByteArray, dnsLen: Int): String? {
        if (dnsLen < 12) return null
        val flags = ((dns[2].toInt() and 0xFF) shl 8) or (dns[3].toInt() and 0xFF)
        val qr = (flags shr 15) and 1
        if (qr != 0) return null
        var pos = 12
        val labels = StringBuilder()
        while (pos < dnsLen) {
            val lab = dns[pos].toInt() and 0xFF
            if (lab == 0) {
                pos++
                break
            }
            if (lab > 63 || pos + lab >= dnsLen) return null
            if (labels.isNotEmpty()) labels.append('.')
            labels.append(String(dns, pos + 1, lab, Charsets.US_ASCII))
            pos += 1 + lab
        }
        if (labels.isEmpty()) return null
        return labels.toString()
    }

    fun buildNxdomainFromQuery(queryDns: ByteArray, queryDnsLen: Int): ByteArray {
        val resp = queryDns.copyOf(queryDnsLen)
        resp[2] = (resp[2].toInt() or 0x80).toByte()
        resp[3] = ((resp[3].toInt() and 0xF0) or 0x03).toByte()
        return resp
    }

    private fun checksumFold(sum: Int): Int {
        var s = sum
        while (s ushr 16 != 0) {
            s = (s and 0xFFFF) + (s ushr 16)
        }
        return s.inv() and 0xFFFF
    }

    fun ipv4Checksum(buf: ByteArray, offset: Int, length: Int): Int {
        var sum = 0
        var i = 0
        while (i < length) {
            val word = ((buf[offset + i].toInt() and 0xFF) shl 8) or (buf[offset + i + 1].toInt() and 0xFF)
            sum += word
            i += 2
        }
        return checksumFold(sum)
    }

    fun udpChecksum(srcIp: ByteArray, dstIp: ByteArray, udpSegment: ByteArray, offset: Int, length: Int): Int {
        var sum = 0
        for (i in 0 until 4 step 2) {
            sum += ((srcIp[i].toInt() and 0xFF) shl 8) or (srcIp[i + 1].toInt() and 0xFF)
        }
        for (i in 0 until 4 step 2) {
            sum += ((dstIp[i].toInt() and 0xFF) shl 8) or (dstIp[i + 1].toInt() and 0xFF)
        }
        sum += 17
        sum += length
        var i = 0
        while (i < length) {
            val word = if (i + 1 < length) {
                ((udpSegment[offset + i].toInt() and 0xFF) shl 8) or (udpSegment[offset + i + 1].toInt() and 0xFF)
            } else {
                (udpSegment[offset + i].toInt() and 0xFF) shl 8
            }
            sum += word
            i += 2
        }
        return checksumFold(sum)
    }

    fun buildIpv4UdpDnsReply(
        originalIp: ByteArray,
        dnsPayload: ByteArray,
        dnsPayloadLen: Int
    ): ByteArray {
        val ipHdrLen = ipv4HeaderLength(originalIp)
        val (srcIp, dstIp) = ipSrcDst(originalIp)
        val (clientUdpSrc, _) = udpPorts(originalIp, ipHdrLen)
        val udpLen = 8 + dnsPayloadLen
        val totalLen = 20 + udpLen
        val out = ByteArray(totalLen)
        out[0] = 0x45
        out[1] = 0
        out[2] = ((totalLen shr 8) and 0xFF).toByte()
        out[3] = (totalLen and 0xFF).toByte()
        out[4] = originalIp[4]
        out[5] = originalIp[5]
        out[6] = 0x40
        out[7] = 0
        out[8] = 64.toByte()
        out[9] = 17
        out[10] = 0
        out[11] = 0
        System.arraycopy(dstIp, 0, out, 12, 4)
        System.arraycopy(srcIp, 0, out, 16, 4)
        val ipChk = ipv4Checksum(out, 0, 20)
        out[10] = ((ipChk shr 8) and 0xFF).toByte()
        out[11] = (ipChk and 0xFF).toByte()

        val uo = 20
        out[uo] = ((53 shr 8) and 0xFF).toByte()
        out[uo + 1] = (53 and 0xFF).toByte()
        out[uo + 2] = ((clientUdpSrc shr 8) and 0xFF).toByte()
        out[uo + 3] = (clientUdpSrc and 0xFF).toByte()
        out[uo + 4] = ((udpLen shr 8) and 0xFF).toByte()
        out[uo + 5] = (udpLen and 0xFF).toByte()
        out[uo + 6] = 0
        out[uo + 7] = 0
        System.arraycopy(dnsPayload, 0, out, uo + 8, dnsPayloadLen)

        var udpChk = udpChecksum(dstIp, srcIp, out, uo, udpLen)
        if (udpChk == 0) udpChk = 0xFFFF
        out[uo + 6] = ((udpChk shr 8) and 0xFF).toByte()
        out[uo + 7] = (udpChk and 0xFF).toByte()
        return out
    }
}
