package com.ved.cleannet

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.VpnService
import android.os.Handler
import android.os.Looper
import android.os.Build
import android.os.ParcelFileDescriptor
import android.util.Log
import androidx.core.app.NotificationCompat
import java.io.FileInputStream
import java.io.FileOutputStream
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Local VPN that only captures traffic to well-known DNS resolvers (see [DNS_IPV4_ROUTES]),
 * inspects UDP port 53 queries, and returns NXDOMAIN for blocked hostnames.
 *
 * **Limitations (MVP):**
 * - Only UDP/53 (classic DNS). Private DNS (DNS-over-TLS) or router DNS may bypass this.
 * - User should set system DNS to one of the routed IPs (e.g. 8.8.8.8) or rely on [Builder.addDnsServer].
 */
class DnsVpnService : VpnService() {

    private var tunInterface: ParcelFileDescriptor? = null
    private var tunnelThread: Thread? = null
    private val running = AtomicBoolean(false)
    /** Ensures we only tear down foreground + stop once (tunnel thread vs. user stop). */
    private val stopCleanupPosted = AtomicBoolean(false)
    private val mainHandler = Handler(Looper.getMainLooper())

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        Blocklist.init(applicationContext)
        PolicyEngine.init(applicationContext)

        when (intent?.action) {
            ACTION_STOP -> {
                stopTunnel()
                stopForegroundAndSelf()
                return START_NOT_STICKY
            }
        }

        try {
            val notification = buildNotification()
            if (Build.VERSION.SDK_INT >= 34) {
                startForeground(
                    NOTIFICATION_ID,
                    notification,
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC
                )
            } else {
                startForeground(NOTIFICATION_ID, notification)
            }
        } catch (e: SecurityException) {
            Log.e(TAG, "startForeground failed", e)
            stopSelf()
            return START_NOT_STICKY
        }

        if (running.get()) return START_STICKY

        running.set(true)
        tunnelThread = Thread({ runTunnel() }, "cleannet-dns-tunnel").also { it.start() }
        return START_STICKY
    }

    override fun onDestroy() {
        stopTunnel()
        super.onDestroy()
    }

    private fun stopTunnel() {
        running.set(false)
        try {
            tunInterface?.close()
        } catch (_: Exception) {
        }
        tunInterface = null
        tunnelThread?.interrupt()
        tunnelThread = null
    }

    private fun runTunnel() {
        val builder = Builder()
            .setSession("CleanNet DNS")
            .addAddress(VPN_ADDRESS, 32)

        for (dns in DNS_IPV4_ROUTES) {
            builder.addRoute(dns, 32)
        }
        builder.addDnsServer(PRIMARY_DNS)

        val pfd = try {
            builder.establish()
        } catch (e: Exception) {
            Log.e(TAG, "VPN establish() failed", e)
            null
        }
        if (pfd == null) {
            Log.e(TAG, "VPN interface is null (establish failed or denied)")
            running.set(false)
            stopForegroundAndSelf()
            return
        }
        tunInterface = pfd

        val input = FileInputStream(pfd.fileDescriptor)
        val output = FileOutputStream(pfd.fileDescriptor)
        val buffer = ByteArray(32767)

        try {
            while (running.get()) {
                val len = try {
                    input.read(buffer)
                } catch (_: Exception) {
                    -1
                }
                if (len <= 0) break
                try {
                    handlePacket(buffer, len, output)
                } catch (_: Exception) {
                }
            }
        } finally {
            try {
                input.close()
            } catch (_: Exception) {
            }
            try {
                output.close()
            } catch (_: Exception) {
            }
            try {
                pfd.close()
            } catch (_: Exception) {
            }
            tunInterface = null
        }

        running.set(false)
        stopForegroundAndSelf()
    }

    /**
     * Must clear foreground state before [stopSelf], otherwise Android 12+ can crash or throw
     * [android.app.ForegroundServiceDidNotStartInTimeException] / bad state when the tunnel never comes up.
     */
    private fun stopForegroundAndSelf() {
        if (!stopCleanupPosted.compareAndSet(false, true)) return
        mainHandler.post {
            try {
                stopForeground(Service.STOP_FOREGROUND_REMOVE)
            } catch (_: Exception) {
            }
            stopSelf()
        }
    }

    private fun handlePacket(packet: ByteArray, len: Int, out: FileOutputStream) {
        if (!IpDnsPacket.isIpv4(packet, len)) return
        val total = IpDnsPacket.ipTotalLength(packet)
        val n = minOf(len, total)
        if (IpDnsPacket.ipProtocol(packet) != 17) return
        val ipHdrLen = IpDnsPacket.ipv4HeaderLength(packet)
        if (n < ipHdrLen + 8) return
        val (_, dstPort) = IpDnsPacket.udpPorts(packet, ipHdrLen)
        if (dstPort != 53) return

        val udpLen = IpDnsPacket.udpLength(packet, ipHdrLen)
        val payloadOff = IpDnsPacket.udpPayloadOffset(ipHdrLen)
        val dnsLen = udpLen - 8
        if (dnsLen <= 0 || payloadOff + dnsLen > n) return

        val dns = packet.copyOfRange(payloadOff, payloadOff + dnsLen)
        val host = IpDnsPacket.dnsQueryHostname(dns, dnsLen) ?: return

        GlobalDnsMonitor.onDnsHostname(applicationContext, host)

        if (PolicyEngine.shouldBlockHost(host)) {
            val nx = IpDnsPacket.buildNxdomainFromQuery(dns, dnsLen)
            val reply = IpDnsPacket.buildIpv4UdpDnsReply(packet, nx, nx.size)
            out.write(reply)
            return
        }

        val (_, dstIp) = IpDnsPacket.ipSrcDst(packet)
        val socket = DatagramSocket()
        try {
            protect(socket)
            socket.soTimeout = 10_000
            val target = InetAddress.getByAddress(dstIp)
            val send = DatagramPacket(dns, dnsLen, target, 53)
            socket.send(send)
            val recvBuf = ByteArray(4096)
            val recv = DatagramPacket(recvBuf, recvBuf.size)
            socket.receive(recv)
            val rlen = recv.length
            val reply = IpDnsPacket.buildIpv4UdpDnsReply(packet, recvBuf.copyOf(rlen), rlen)
            out.write(reply)
        } finally {
            socket.close()
        }
    }

    private fun buildNotification(): Notification {
        val nm = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            nm.createNotificationChannel(
                NotificationChannel(
                    CHANNEL_ID,
                    getString(R.string.dns_vpn_channel_name),
                    NotificationManager.IMPORTANCE_LOW
                )
            )
        }
        val pending = PendingIntent.getService(
            this,
            0,
            Intent(this, DnsVpnService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle(getString(R.string.dns_vpn_notification_title))
            .setContentText(getString(R.string.dns_vpn_notification_text))
            .setContentIntent(
                PendingIntent.getActivity(
                    this,
                    0,
                    Intent(this, MainActivity::class.java),
                    PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
                )
            )
            .addAction(0, getString(R.string.dns_vpn_stop), pending)
            .setOngoing(true)
            .build()
    }

    companion object {
        private const val TAG = "DnsVpnService"

        const val ACTION_STOP = "com.ved.cleannet.STOP_DNS_VPN"

        private const val NOTIFICATION_ID = 42
        private const val CHANNEL_ID = "cleannet_dns_vpn"

        /** Virtual tunnel address (must match DNS routes design). */
        private const val VPN_ADDRESS = "10.0.0.2"

        /** System DNS hint — queries are often sent here when using this VPN. */
        private const val PRIMARY_DNS = "8.8.8.8"

        /**
         * Only these destinations are routed through the VPN interface so the rest of the device
         * keeps using the normal network (MVP: avoid full IP forwarding).
         */
        private val DNS_IPV4_ROUTES = arrayOf(
            "8.8.8.8",
            "8.8.4.4",
            "1.1.1.1",
            "1.0.0.1"
        )
    }
}
