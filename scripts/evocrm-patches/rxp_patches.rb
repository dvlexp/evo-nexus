# frozen_string_literal: true
# RXP patches EVO CRM — upstream bug fixes applied at runtime
# Issues: https://github.com/EvolutionAPI/evo-ai-crm-community/issues/6, /7, /8
#         https://github.com/EvolutionAPI/evo-ai-frontend-community/issues/14

Rails.application.config.to_prepare do
  # ------------------------------------------------------------------
  # Bug 1: ContactCompany validator references undefined method
  # ------------------------------------------------------------------
  if defined?(ContactCompany)
    ContactCompany.class_eval do
      unless private_method_defined?(:must_belong_to_same_account) || method_defined?(:must_belong_to_same_account)
        private
        def must_belong_to_same_account; end
      end
    end
    Rails.logger.info "[RXP_PATCH] ContactCompany#must_belong_to_same_account no-op installed"
  end

  # ------------------------------------------------------------------
  # Bug 2: PipelineItemsController#update_custom_fields missing before_action
  # ------------------------------------------------------------------
  if defined?(Api::V1::PipelineItemsController)
    Api::V1::PipelineItemsController.class_eval do
      before_action :set_pipeline_item, only: [:update, :destroy, :move_to_stage, :update_conversation, :update_custom_fields]
      # Allow pipeline_stage_id and merge notes into custom_fields
      private
      def pipeline_item_params
        permitted = params.require(:pipeline_item).permit(:pipeline_stage_id, custom_fields: {})
        if params[:notes].present?
          permitted[:custom_fields] ||= {}
          permitted[:custom_fields][:notes] = params[:notes]
        end
        permitted
      end
    end
    Rails.logger.info "[RXP_PATCH] PipelineItemsController — set_pipeline_item + permit pipeline_stage_id + notes"
  end

  # ------------------------------------------------------------------
  # Bug 3: ContactCompaniesController error_response kwargs → positional
  # ------------------------------------------------------------------
  if defined?(Api::V1::ContactCompaniesController)
    Api::V1::ContactCompaniesController.class_eval do
      def create
        r = Contacts::LinkCompanyService.new(contact: @contact, company: @company).perform
        if r[:success]
          success_response(data: { contact: @contact.slice(:id,:name,:type), company: @company.slice(:id,:name,:type) }, message: "linked")
        else
          error_response(ApiErrorCodes::BUSINESS_RULE_VIOLATION, r[:error])
        end
      end
      def destroy
        r = Contacts::UnlinkCompanyService.new(contact: @contact, company: @company).perform
        if r[:success]
          success_response(data: { contact: @contact.slice(:id,:name,:type), company: @company.slice(:id,:name,:type) }, message: "unlinked")
        else
          error_response(ApiErrorCodes::BUSINESS_RULE_VIOLATION, r[:error])
        end
      end
    end
    Rails.logger.info "[RXP_PATCH] ContactCompaniesController create/destroy fixed"
  end

  # ------------------------------------------------------------------
  # Bug 4: PipelinesController N+1 — kanban 8s → 200ms
  # ------------------------------------------------------------------
  if defined?(Api::V1::PipelinesController)
    Api::V1::PipelinesController.class_eval do
      def index
        @pipelines = Pipeline.all.accessible_by(Current.user).active.includes(
          pipeline_stages: [],
          pipeline_items: [:pipeline_stage, conversation: [:contact,:assignee,:inbox]]
        ).order(:name)
        success_response(
          data: PipelineSerializer.serialize_collection(@pipelines,
            include_stages: true, include_items: false,
            include_tasks_info: false, include_services_info: false),
          message: "Pipelines retrieved")
      end
      def show
        success_response(
          data: PipelineSerializer.serialize(@pipeline,
            include_stages: true, include_items: true,
            include_tasks_info: false, include_services_info: false),
          message: "Pipeline retrieved")
      end
      def fetch_pipeline
        @pipeline = Pipeline.all.includes(
          :created_by, pipeline_stages: [],
          pipeline_items: [:pipeline_stage, :contact, conversation: [:contact,:assignee,:team,:inbox]]
        ).find(params[:id])
      end
    end
    Rails.logger.info "[RXP_PATCH] PipelinesController — N+1 removed"
  end

  # ------------------------------------------------------------------
  # Bug 5: PipelineStage.stage_type missing enum
  # ------------------------------------------------------------------
  if defined?(PipelineStage)
    PipelineStage.class_eval do
      unless defined_enums.key?("stage_type")
        enum stage_type: { active: 0, completed: 1, cancelled: 2 }
      end
    end
    Rails.logger.info "[RXP_PATCH] PipelineStage.stage_type enum"
  end



  # ------------------------------------------------------------------
  # Bug 9: AgentsController passed current_user as 1st arg to
  #   EvoAiCoreService — service signatures expect params/data/id.
  #   EvoAiCoreService.build_headers already resolves Current.user.
  #   Symptom: all /api/v1/agents endpoints returned 500
  #   (NoMethodError: undefined method 'empty?' for an instance of User).
  # ------------------------------------------------------------------
  if defined?(Api::V1::AgentsController)
    Api::V1::AgentsController.class_eval do
      def index
        result = EvoAiCoreService.list_agents(index_params)
        render json: result
      end
      def create
        result = EvoAiCoreService.create_agent(agent_params)
        render json: result, status: :created
      end
      def update
        result = EvoAiCoreService.update_agent(params[:id], agent_params)
        render json: result
      end
      def destroy
        EvoAiCoreService.delete_agent(params[:id])
        head :no_content
      end
    end
    Rails.logger.info "[RXP_PATCH] AgentsController — current_user removed from EvoAiCoreService calls"
  end

  # ------------------------------------------------------------------
  # Bug 10 (LGPD): Sidekiq / ActionController logavam payloads WhatsApp
  #   completos com telefones, nomes e conteúdo de mensagens em clear.
  #   Adiciona filtros para mascarar esses campos em todos os logs de
  #   parâmetros Rails (Controllers + ActiveJob).
  # ------------------------------------------------------------------
  Rails.application.config.filter_parameters += [
    # WhatsApp (Evolution API webhook payload)
    :remoteJid, :participantAlt, :participant, :pushName, :phone, :phone_number,
    :sender, :senderKeyDistributionMessage, :mediaKey, :fileEncSha256, :fileSha256,
    :jpegThumbnail, :directPath, :url,
    # Message content (qualquer nested)
    :conversation, :extendedTextMessage, :imageMessage, :videoMessage,
    :audioMessage, :documentMessage, :stickerMessage, :locationMessage,
    :contactMessage, :liveLocationMessage, :caption, :text, :body,
    # Contato / Identificação
    :email, :phone_number, :phones, :mobile, :cpf, :cnpj, :document,
    :identifier, :source_id
  ]
  Rails.logger.info "[RXP_PATCH] filter_parameters expanded — LGPD: WhatsApp payload masked"



  # ------------------------------------------------------------------
  # Bug 11 (v3 — remoteJidAlt + phone_number_from_jid, PR #112 approach)
  # v2 patched jid_type only via fetchProfile (sync HTTP, can timeout).
  # v3 improvements:
  #   1. effective_remote_jid uses remoteJidAlt (already in webhook payload,
  #      zero HTTP round-trip) before falling back to fetchProfile.
  #   2. phone_number_from_jid also patched — was still reading @raw_message
  #      directly, causing contacts created with LID digits as phone number.
  #   3. In-place mutation centralized in effective_remote_jid so ALL
  #      downstream methods benefit automatically.
  # ref: evolution-foundation/evo-ai-crm-community PR #112
  # ------------------------------------------------------------------
  if defined?(Whatsapp::EvolutionHandlers::Helpers)
    Whatsapp::EvolutionHandlers::Helpers.module_eval do
      unless private_method_defined?(:resolve_lid_to_phone_jid)
        def resolve_lid_to_phone_jid(lid_number)
          cache_key = "rxp:evolution:lid_resolve:#{lid_number}"
          cached = ::Redis::Alfred.get(cache_key)
          return cached if cached.present?

          api_url = @inbox&.channel&.provider_config&.dig('api_url')
          admin = @inbox&.channel&.provider_config&.dig('admin_token')
          instance = @inbox&.channel&.provider_config&.dig('instance_name')
          return nil if api_url.blank? || admin.blank? || instance.blank?

          uri = URI.parse("#{api_url.chomp('/')}/chat/fetchProfile/#{instance}")
          http = Net::HTTP.new(uri.host, uri.port)
          http.use_ssl = (uri.scheme == 'https')
          http.open_timeout = 5
          http.read_timeout = 5

          req = Net::HTTP::Post.new(uri)
          req['apikey'] = admin
          req['Content-Type'] = 'application/json'
          req.body = { number: "#{lid_number}@lid" }.to_json

          res = http.request(req)
          return nil unless res.code.to_i.between?(200, 299)

          body = JSON.parse(res.body) rescue {}
          wuid = body['wuid']
          return nil unless wuid.is_a?(String) && wuid.include?('@s.whatsapp.net')

          ::Redis::Alfred.setex(cache_key, wuid, 7.days)
          wuid
        rescue StandardError => e
          Rails.logger.warn "[RXP_PATCH] LID resolve failed for #{lid_number}: #{e.class} #{e.message}"
          nil
        end
      end

      unless private_method_defined?(:effective_remote_jid)
        def effective_remote_jid
          jid = @raw_message[:remoteJid] || @raw_message.dig(:key, :remoteJid)
          return jid unless jid.to_s.end_with?('@lid')

          # PR #112: prefer remoteJidAlt (already in payload, no HTTP round-trip)
          alt = @raw_message[:remoteJidAlt] || @raw_message.dig(:key, :remoteJidAlt)
          resolved = if alt.present? && !alt.to_s.end_with?('@lid')
                       lid_digits = jid.split('@').first.split(':').first
                       begin
                         ::Redis::Alfred.setex("rxp:evolution:lid_resolve:#{lid_digits}", alt, 7.days)
                       rescue StandardError
                         nil
                       end
                       Rails.logger.info "[RXP_PATCH] LID resolved via remoteJidAlt: #{jid} → #{alt}"
                       alt
                     else
                       lid_digits = jid.split('@').first.split(':').first
                       resolve_lid_to_phone_jid(lid_digits) || jid
                     end

          # Mutate in-place so ALL downstream methods see the real JID
          if @raw_message.is_a?(Hash)
            @raw_message[:remoteJid] = resolved if @raw_message[:remoteJid].to_s.end_with?('@lid')
            if @raw_message.dig(:key, :remoteJid).to_s.end_with?('@lid')
              @raw_message[:key][:remoteJid] = resolved
            end
          end

          resolved
        end
      end

      unless private_method_defined?(:jid_type_without_lid_patch)
        alias_method :jid_type_without_lid_patch, :jid_type
        def jid_type
          effective_remote_jid # triggers in-place mutation; non-LID messages are no-op
          jid_type_without_lid_patch
        end
      end

      unless private_method_defined?(:phone_number_from_jid_without_lid_patch)
        alias_method :phone_number_from_jid_without_lid_patch, :phone_number_from_jid
        def phone_number_from_jid
          effective_remote_jid # triggers in-place mutation; non-LID messages are no-op
          phone_number_from_jid_without_lid_patch
        end
      end
    end
    Rails.logger.info "[RXP_PATCH] EvolutionHandlers#jid_type+phone_number_from_jid — LID→remoteJidAlt+fetchProfile v3 (bug 11, PR #112)"
  end

  # ------------------------------------------------------------------
  # Bug 12: OAuth Applications index returns plain array, frontend expects
  # wrapped {success, data, meta: {pagination}} → "Cannot read properties of
  # undefined (reading 'pagination')" in console, page shows empty list.
  # ------------------------------------------------------------------
  if defined?(Api::V1::Oauth::ApplicationsController)
    Api::V1::Oauth::ApplicationsController.class_eval do
      def index
        apps = OauthApplication.all.order(:created_at).map { |app| application_serializer(app) }
        render json: {
          success: true,
          data: apps,
          meta: {
            pagination: {
              current_page: 1,
              total_pages: 1,
              total_count: apps.length,
              per_page: apps.length
            }
          },
          message: ''
        }
      end
    end
    Rails.logger.info "[RXP_PATCH] OauthApplicationsController#index wrapped with {success,data,meta.pagination}"
  end

  # ------------------------------------------------------------------
  # Bug 13 (RXP Aurora Copilota): block public auto-reply from bots that
  # have bot_config['private_only'] == true. Aurora is meant to ONLY post
  # private notes (rascunhos de resposta) — it must NEVER send a message
  # to the customer. The upstream MessageCreator hardcodes message_type
  # to 'outgoing' regardless. We short-circuit create_bot_reply for any
  # bot whose bot_config flags private_only=true.
  # Incident 2026-04-28: Aurora vazou rascunho técnico no WhatsApp
  # da Débora Rocco e resposta solta pro Tom (5551995035947).
  # ------------------------------------------------------------------
  if defined?(AgentBots::MessageCreator)
    AgentBots::MessageCreator.class_eval do
      alias_method :create_bot_reply_without_private_only, :create_bot_reply

      def create_bot_reply(content, conversation, force: false)
        if @agent_bot.bot_config&.dig('private_only') == true
          Rails.logger.warn(
            "[RXP_PATCH] Aurora private_only: dropping public reply attempt from bot " \
            "#{@agent_bot.id} (#{@agent_bot.name}) for conversation #{conversation.id}. " \
            "Content preview: #{content.to_s[0, 80]}"
          )
          return nil
        end
        create_bot_reply_without_private_only(content, conversation, force: force)
      end
    end
    Rails.logger.info '[RXP_PATCH] AgentBots::MessageCreator#create_bot_reply gated by bot_config["private_only"]'
  end

  # ------------------------------------------------------------------
  # Bug 14 (RXP Aurora Copilota — inactivity_only mode): skip on-incoming
  # dispatch when bot_config['inactivity_only'] == true. The bot will only
  # be triggered by the InactivityCheckSchedulerJob after the configured
  # idle period. This lets Aurora wait for conversation lull before
  # generating a single contextualized private note (saves tokens).
  # Setting allowed_conversation_statuses to a non-matching value would
  # ALSO disable the inactivity flow (shared filter), so we patch here
  # instead. Adopted 2026-04-28.
  # ------------------------------------------------------------------
  if defined?(BotRuntime::DelegationService)
    BotRuntime::DelegationService.class_eval do
      alias_method :delegate_without_inactivity_only, :delegate

      def delegate
        if @agent_bot.bot_config&.dig('inactivity_only') == true
          Rails.logger.info(
            "[RXP_PATCH] Aurora inactivity_only: skipping on-incoming dispatch for bot " \
            "#{@agent_bot.id} (#{@agent_bot.name}) conversation=#{@conversation.display_id}. " \
            "Will wait for InactivityCheckSchedulerJob to trigger after idle period."
          )
          return nil
        end
        delegate_without_inactivity_only
      end
    end
    Rails.logger.info '[RXP_PATCH] BotRuntime::DelegationService#delegate gated by bot_config["inactivity_only"]'
  end

  # ------------------------------------------------------------------
  # Bug 15 (RXP Aurora Copilota — auto-status by categoria): after Aurora
  # creates a private note, parse the [Aurora] **categoria** prefix and
  # transition the conversation status accordingly:
  #   - spam-ruido / informativo → resolved (no action needed)
  #   - comercial-* / operacional → pending (Daniel needs to act)
  # Only fires for messages from bots with bot_config['private_only']=true,
  # so it's scoped to Aurora-class agents. Adopted 2026-04-28.
  # ------------------------------------------------------------------
  if defined?(Message)
    AURORA_STATUS_BY_CATEGORIA = {
      'spam-ruido' => 'resolved',
      'informativo' => 'resolved',
      'comercial-novo' => 'pending',
      'comercial-followup' => 'pending',
      'comercial-pago' => 'pending',
      'operacional' => 'pending'
    }.freeze

    Message.class_eval do
      after_create_commit :rxp_aurora_auto_status_transition

      def rxp_aurora_auto_status_transition
        return unless private == true
        return unless sender_type == 'AgentBot'

        agent_bot = sender
        return unless agent_bot.respond_to?(:bot_config)
        return unless agent_bot.bot_config&.dig('private_only') == true

        match = content.to_s.match(/\[Aurora\]\s*\*\*([\w-]+)\*\*/i)
        return unless match

        categoria = match[1].to_s.downcase.strip
        new_status = AURORA_STATUS_BY_CATEGORIA[categoria]
        unless new_status
          Rails.logger.info "[RXP_PATCH] Aurora auto-status: unknown categoria '#{categoria}' (msg #{id}), no transition"
          return
        end

        return if conversation.status == new_status

        Rails.logger.info(
          "[RXP_PATCH] Aurora auto-status: conversation #{conversation.id} " \
          "categoria='#{categoria}' #{conversation.status} → #{new_status}"
        )
        begin
          conversation.update!(status: new_status)
        rescue StandardError => e
          Rails.logger.warn "[RXP_PATCH] Aurora auto-status: failed to transition conv #{conversation.id}: #{e.class}: #{e.message}"
        end
      end
    end
    Rails.logger.info '[RXP_PATCH] Message#rxp_aurora_auto_status_transition installed (bug 15)'
  end

  # ------------------------------------------------------------------
  # Bug 16 (RXP Evolution media download via getBase64FromMediaMessage):
  # Evolution v2.3.7 webhook payload does NOT include base64 nor mediaUrl
  # for audio/image/video/document/sticker messages. The original
  # AttachmentProcessor#download_attachment_file logs "No media found"
  # and drops the attachment silently. Result: 100% of WhatsApp media
  # since 2026-04-22 was discarded.
  #
  # Fix: prepend a fallback that calls the Evolution endpoint
  #   POST {api_url}/chat/getBase64FromMediaMessage/{instance}
  # which returns the decrypted media as base64. We then reuse the
  # existing create_tempfile_from_base64 helper.
  #
  # Adopted 2026-04-29.
  # ------------------------------------------------------------------
  module RxpEvolutionMediaDownload
    MEDIA_MESSAGE_KEYS = %w[audioMessage imageMessage videoMessage documentMessage stickerMessage documentWithCaptionMessage].freeze

    def download_attachment_file
      result = super
      return result if result

      message = @raw_message[:message] || {}
      has_media = MEDIA_MESSAGE_KEYS.any? { |k| message[k.to_sym].present? || message[k].present? }
      return nil unless has_media

      pc = inbox.channel.provider_config || {}
      api_url = pc['api_url'].to_s.chomp('/')
      api_token = pc['admin_token'].to_s
      instance_name = pc['instance_name'].to_s
      message_id = raw_message_id.to_s

      if api_url.empty? || api_token.empty? || instance_name.empty? || message_id.empty?
        Rails.logger.warn "[RXP_PATCH] Evolution getBase64 fallback: missing config for msg #{message_id}"
        return nil
      end

      Rails.logger.info "[RXP_PATCH] Evolution getBase64 fallback: fetching media for msg #{message_id}"
      response = HTTParty.post(
        "#{api_url}/chat/getBase64FromMediaMessage/#{instance_name}",
        headers: { 'apikey' => api_token, 'Content-Type' => 'application/json' },
        body: { message: { key: { id: message_id } } }.to_json,
        timeout: 30
      )

      unless [200, 201].include?(response.code)
        Rails.logger.warn "[RXP_PATCH] Evolution getBase64: HTTP #{response.code} for msg #{message_id}"
        return nil
      end

      data = JSON.parse(response.body)
      base64_data = data['base64']
      if base64_data.blank?
        Rails.logger.warn "[RXP_PATCH] Evolution getBase64: empty base64 for msg #{message_id}"
        return nil
      end

      Rails.logger.info "[RXP_PATCH] Evolution getBase64: got #{base64_data.length}b for msg #{message_id} (#{data['mimetype']})"
      create_tempfile_from_base64(base64_data)
    rescue StandardError => e
      Rails.logger.error "[RXP_PATCH] Evolution getBase64 error for msg #{raw_message_id}: #{e.class}: #{e.message}"
      nil
    end
  end

  if defined?(Whatsapp::EvolutionHandlers::AttachmentProcessor)
    Whatsapp::EvolutionHandlers::AttachmentProcessor.prepend RxpEvolutionMediaDownload
    Rails.logger.info '[RXP_PATCH] EvolutionHandlers::AttachmentProcessor — getBase64FromMediaMessage fallback (bug 16)'
  end

  # ------------------------------------------------------------------
  # Bug 16b (RXP EvoGo media download — getBase64FromMediaMessage):
  # EvoGo webhook payloads may include a mediaUrl that is a signed/internal
  # URL unavailable outside the EvoGo host. When Down.download fails or
  # no URL is present, this fallback calls the EvoGo API endpoint
  #   POST {api_url}/chat/getBase64FromMediaMessage/{instance}
  # to retrieve the decrypted media as base64.
  #
  # EvoGo provider_config fields used (same as Evolution API):
  #   api_url        → https://whatsapp2.resultadosexponenciais.com.br
  #   admin_token    → API key header 'apikey'
  #   instance_name  → instance slug (e.g. "dvl")
  #
  # Adopted 2026-05-25.
  # ------------------------------------------------------------------
  module RxpEvolutionGoMediaDownload
    EVOGO_MEDIA_TYPES = %w[image video audio ptt document sticker].freeze

    def download_attachment_file
      result = super
      return result if result

      # Only fire for media messages
      media_type = @evolution_go_info&.dig(:MediaType).to_s.downcase
      return nil unless EVOGO_MEDIA_TYPES.include?(media_type)

      pc = inbox.channel.provider_config || {}
      api_url = pc['api_url'].to_s.chomp('/')
      api_token = pc['admin_token'].to_s
      instance_name = pc['instance_name'].to_s
      message_id = raw_message_id.to_s

      if api_url.empty? || api_token.empty? || instance_name.empty? || message_id.empty?
        Rails.logger.warn "[RXP_PATCH] EvoGo getBase64 fallback: missing config for msg #{message_id}"
        return nil
      end

      Rails.logger.info "[RXP_PATCH] EvoGo getBase64 fallback: fetching media for msg #{message_id} (type: #{media_type})"
      response = HTTParty.post(
        "#{api_url}/chat/getBase64FromMediaMessage/#{instance_name}",
        headers: { 'apikey' => api_token, 'Content-Type' => 'application/json' },
        body: { message: { key: { id: message_id } } }.to_json,
        timeout: 30
      )

      unless [200, 201].include?(response.code)
        Rails.logger.warn "[RXP_PATCH] EvoGo getBase64: HTTP #{response.code} for msg #{message_id}"
        return nil
      end

      data = JSON.parse(response.body)
      base64_data = data['base64']
      if base64_data.blank?
        Rails.logger.warn "[RXP_PATCH] EvoGo getBase64: empty base64 for msg #{message_id}"
        return nil
      end

      Rails.logger.info "[RXP_PATCH] EvoGo getBase64: got #{base64_data.length}b for msg #{message_id} (#{data['mimetype']})"

      # Decode base64 and write to tempfile (EvoGo MessagesUpsert does not have
      # create_tempfile_from_base64 helper, so we inline it here)
      extension = ".#{media_extension}"
      tmpfile = Tempfile.new([message_id, extension])
      tmpfile.binmode
      tmpfile.write(Base64.decode64(base64_data.gsub(/^data:.*?;base64,/, '')))
      tmpfile.rewind

      content_type_str = data['mimetype'] || determine_content_type
      filename_str = "#{message_id}#{extension}"

      tmpfile.define_singleton_method(:original_filename) { filename_str }
      tmpfile.define_singleton_method(:content_type) { content_type_str }
      tmpfile.define_singleton_method(:size) { File.size(path) }

      tmpfile
    rescue StandardError => e
      Rails.logger.error "[RXP_PATCH] EvoGo getBase64 error for msg #{raw_message_id}: #{e.class}: #{e.message}"
      nil
    end
  end

  if defined?(Whatsapp::EvolutionGoHandlers::MessagesUpsert)
    Whatsapp::EvolutionGoHandlers::MessagesUpsert.prepend RxpEvolutionGoMediaDownload
    Rails.logger.info '[RXP_PATCH] EvolutionGoHandlers::MessagesUpsert — getBase64FromMediaMessage fallback (bug 16b)'
  end

  # ------------------------------------------------------------------
  # Bug 17 (RXP companies_list returns 2/242): the upstream
  # ContactsController#companies_list applies Contact.resolved_contacts
  # which requires email/phone_number/identifier OR contact_inboxes
  # presence. Companies are entities (not chat endpoints), so they
  # rarely have any of these — only 2 of 242 companies were appearing
  # in the autocomplete when editing a contact. Same scope blocks the
  # "Pesquisar empresa" dropdown in the contact edit modal.
  #
  # Fix: return ALL companies with a name, ordered alphabetically. No
  # filtering by resolved attributes. 242 records is well within the
  # acceptable response size for this autocomplete endpoint.
  #
  # Adopted 2026-04-29.
  # ------------------------------------------------------------------
  if defined?(Api::V1::ContactsController)
    Api::V1::ContactsController.class_eval do
      def companies_list
        companies = Contact.where(type: 'company')
                           .where("BTRIM(COALESCE(name,'')) <> ''")
                           .select(:id, :name, :type, :location, :country_code)
                           .order(:name)

        success_response(
          data: companies.map { |c| { id: c.id, name: c.name } },
          message: 'Companies list retrieved successfully'
        )
      end
    end
    Rails.logger.info '[RXP_PATCH] ContactsController#companies_list returns all named companies (bug 17)'
  end

  # ------------------------------------------------------------------
  # Bug 18 (RXP Aurora WHATSAPP-BUSINESS): Evolution API does NOT emit
  # MESSAGES_UPSERT for outgoing messages on WHATSAPP-BUSINESS (Meta Cloud
  # API) instances — instead it sends SEND_MESSAGE events. Upstream
  # IncomingMessageEvolutionService#perform had no handler for
  # 'send.message', so all aurora bot replies were silently discarded
  # (logged as "Unsupported event type").
  # The payload structure for send.message mirrors messages.upsert, with
  # key.fromMe=true. The existing process_messages_upsert + helpers#incoming?
  # already handles fromMe=true → :outgoing message type.
  # Fix: route 'send.message' to process_messages_upsert.
  # Adopted 2026-05-30.
  # ------------------------------------------------------------------
  if defined?(Whatsapp::IncomingMessageEvolutionService)
    Whatsapp::IncomingMessageEvolutionService.class_eval do
      def perform
        event_type = processed_params[:event]
        Rails.logger.info "Evolution API: Processing event #{event_type} for instance #{processed_params[:instance]}"
        Rails.logger.debug { "Evolution API: Full payload: #{processed_params.inspect}" }

        case event_type
        when 'messages.upsert', 'send.message'
          process_messages_upsert
        when 'messages.update'
          process_messages_update
        when 'contacts.update'
          process_contacts_update
        when 'chats.update', 'chats.upsert'
          Rails.logger.info "Evolution API: Chat event #{event_type} - not processing (chat-level events)"
        when 'qrcode.updated'
          Rails.logger.info 'Evolution API: QR Code updated'
        when 'connection.update'
          process_connection_update
        when 'logout.instance'
          process_logout_instance
        else
          Rails.logger.warn "Evolution API: Unsupported event type: #{event_type}"
        end
      end
    end
    Rails.logger.info '[RXP_PATCH] IncomingMessageEvolutionService#perform — send.message routed to process_messages_upsert (bug 18)'
  end

  # ------------------------------------------------------------------
  # Bug 19 (RXP Aurora templates via Evolution API): upstream
  # EvolutionService#sync_templates was a no-op and #create_template
  # silently stored templates as APPROVED locally without calling Meta.
  # For WHATSAPP-BUSINESS instances, Evolution API exposes:
  #   GET  {api_url}/template/find/{instance}  → list with real Meta status
  #   POST {api_url}/template/create/{instance} → submit template to Meta
  # Fixes:
  #   sync_templates → calls GET and upserts all templates via TemplateSync
  #   create_template → calls POST, syncs response, falls back to local PENDING
  # Adopted 2026-05-30.
  # ------------------------------------------------------------------
  if defined?(Whatsapp::Providers::EvolutionService)
    Whatsapp::Providers::EvolutionService.class_eval do
      include Whatsapp::Providers::Concerns::TemplateSync unless
        include?(Whatsapp::Providers::Concerns::TemplateSync) rescue false

      def sync_templates
        return if send(:api_base_path).blank? || send(:instance_name).blank?

        inst = send(:instance_name)
        base = send(:api_base_path)
        hdrs = send(:api_headers)

        Rails.logger.info "Evolution: Syncing templates from API for #{inst}"
        response = HTTParty.get("#{base}/template/find/#{inst}", headers: hdrs, timeout: 30)

        unless response.success?
          Rails.logger.error "Evolution: Template sync failed - HTTP #{response.code}: #{response.body}"
          return
        end

        templates = response.parsed_response
        templates = templates['templates'] if templates.is_a?(Hash) && templates.key?('templates')
        templates = [templates] unless templates.is_a?(Array)
        templates = templates.select { |t| t.is_a?(Hash) && t['name'].present? }

        synced = 0
        templates.each { |t| sync_template_to_database(t); synced += 1 }
        Rails.logger.info "Evolution: Synced #{synced} templates for #{inst}"
      rescue StandardError => e
        Rails.logger.error "Evolution: sync_templates error - #{e.message}"
      end

      def create_template(template_data)
        base = send(:api_base_path)
        inst = send(:instance_name)
        hdrs = send(:api_headers)

        if base.blank? || inst.blank?
          template_data['status'] ||= 'PENDING'
          return rxp_store_template_locally(template_data)
        end

        Rails.logger.info "Evolution: Submitting template to Meta via API - #{template_data['name']}"
        response = HTTParty.post("#{base}/template/create/#{inst}",
                                 headers: hdrs, body: template_data.to_json, timeout: 30)

        if response.success?
          result = response.parsed_response
          merged = result.is_a?(Hash) ? template_data.merge(result) : template_data
          merged['status'] ||= 'PENDING'
          sync_template_to_database(merged)
          merged
        else
          Rails.logger.error "Evolution: Template creation failed - HTTP #{response.code}: #{response.body}"
          rxp_store_template_locally(template_data.merge('status' => 'PENDING'))
        end
      rescue StandardError => e
        Rails.logger.error "Evolution: create_template error - #{e.message}"
        rxp_store_template_locally(template_data.merge('status' => 'PENDING'))
      end

      def rxp_store_template_locally(template_data)
        sync_template_to_database(template_data)
        template_data
      end
    end
    Rails.logger.info '[RXP_PATCH] EvolutionService#sync_templates + #create_template — Evolution API integration (bug 19)'
  end


# ===========================================================================
# Bug 20 (v1) -- ConditionsFilterService: query_operator leading fix
# ---------------------------------------------------------------------------
# EvoAI CRM stores query_operator on the RECEIVING condition (leading format):
#   [{assignee_id, q_op: null}, {labels, q_op: "AND"}]
# But upstream code appends q_op TRAILING (Chatwoot format), producing:
#   "assignee_id IN (:v0)  NOT EXISTS(...)" - PG::SyntaxError missing AND
# Fix: override build_query_string to strip q_op from hash (so underlying
# methods do not append it) then prepend it to the fragment.
# ===========================================================================
  if defined?(AutomationRules::ConditionsFilterService)
    AutomationRules::ConditionsFilterService.module_eval do
      unless method_defined?(:build_query_string_without_qop_fix)
        alias_method :build_query_string_without_qop_fix, :build_query_string
        def build_query_string(filters, query_hash, current_index)
          qop = (query_hash['query_operator'] || query_hash[:query_operator]).to_s.strip
          stripped = query_hash.with_indifferent_access.merge('query_operator' => nil)
          result = build_query_string_without_qop_fix(filters, stripped, current_index)
          qop.present? && !@query_string.strip.empty? ? " #{qop} #{result.strip} " : result
        end
      end
    end
    Rails.logger.info '[RXP_PATCH] ConditionsFilterService#build_query_string -- query_operator leading->prepend v2 (bug 20)'
  end

# ===========================================================================
# Bug 21 (v1) -- PermissionFilterService nil user guard (PR #143)
# ---------------------------------------------------------------------------
# Service-token callers (e.g. evo-ai-processor) never set Current.user, so
# user.nil? -> user_role calls nil.role -> NoMethodError -> 500 on
# GET /api/v1/contacts/:id/conversations, breaking transfer_to_human.
# Fix: treat nil user as fully trusted (internal) and skip inbox filtering.
# ===========================================================================
  if defined?(Conversations::PermissionFilterService)
    Conversations::PermissionFilterService.prepend(Module.new do
      def perform
        return conversations if user.nil?
        super
      end
    end)
    Rails.logger.info '[RXP_PATCH] PermissionFilterService#perform -- nil user guard (PR #143, bug 21)'
  end

# ===========================================================================
# Bug 22 -- REMOVIDO em rc6 upgrade (2026-07-06)
# ---------------------------------------------------------------------------
# rc6 upstream (PR #145 + EVO-1928) implementou o mesmo `render json:` E
# refatorou #create pra chamar `incoming_label_tokens` (normaliza labelId,
# label, title alem de labels[]), tratamento superior ao nosso patch.
# Nosso module_eval sobrescreveria #create perdendo a normalizacao EVO-1928.
# Trail analysis: workspace/development/features/rxp-4-fluxos-fix/[C]trail-rc6-diff-analysis.md
# ===========================================================================

# ===========================================================================
# Bug 23 (v1) -- Conversations::FilterService assignee_type handler
# ---------------------------------------------------------------------------
# The frontend filter modal sends assignee_type as attribute_key with values
# [me/assigned/unassigned/all]. filter_keys.yml only defines assignee_id ->
# model_filters['assignee_type'] = nil -> custom_attribute_query returns '' ->
# InvalidAttribute raised -> controller returns 400 -> frontend shows all convs
# instead of filtered results.
# Fix: override build_condition_query to handle assignee_type before delegating
# to the original method. Uses @filter_values for parameterized 'me' query.
#
# NOTE: The real root cause is in the frontend bundle (ChatPage-BV93Mg_x.js).
# Function _o() in the filter serializer had no case for "assignee_type" --
# the filter was silently dropped. jo() routes single assignee_type filters to
# GET /conversations (not POST), so _o() must emit ?assignee_type=value.
# Frontend fix: added case"assignee_type" to _o() in the bind-mounted bundle.
# This backend patch still applies when jo() routes to POST /conversations/filter
# (e.g. multi-filter combinations including assignee_type).
# ===========================================================================
  if defined?(Conversations::FilterService)
    Conversations::FilterService.module_eval do
      unless method_defined?(:build_condition_query_without_assignee_type_fix)
        alias_method :build_condition_query_without_assignee_type_fix, :build_condition_query

        def build_condition_query(model_filters, query_hash, current_index)
          attr_key = (query_hash['attribute_key'] || query_hash[:attribute_key]).to_s

          if attr_key == 'assignee_type'
            value = ((query_hash['values'] || query_hash[:values]) || []).first.to_s
            case value
            when 'me'
              key = "assignee_type_me_#{current_index}"
              @filter_values[key] = @user.id
              "conversations.assignee_id = :#{key}"
            when 'assigned'
              'conversations.assignee_id IS NOT NULL'
            when 'unassigned'
              'conversations.assignee_id IS NULL'
            else
              ''
            end
          else
            build_condition_query_without_assignee_type_fix(model_filters, query_hash, current_index)
          end
        end
      end
    end
    Rails.logger.info '[RXP_PATCH] Conversations::FilterService#build_condition_query -- assignee_type handler v1 (bug 23)'
  end

# ===========================================================================
# Bug 24 (v1) -- EvolutionGoHandlers::MessagesUpsert: LID stored as source_id
# ---------------------------------------------------------------------------
# EvoGo implemented a LID->JID swap: when sender arrives as @lid, EvoGo swaps
# so Sender = JID (@s.whatsapp.net) and SenderAlt = LID (@lid).
# Before the swap, SenderAlt held the real JID -> using it as source_id was
# correct. After the swap, SenderAlt holds the LID -> source_id stored as LID
# (e.g. "222221842833426@lid") -> frontend can't parse as phone number ->
# conversation shows "sem canal" (no channel display).
# Same bug: build_contact_attributes and update_contact_information set
# contact.identifier = LID -> set_contact_for_outgoing can't match outgoing
# echo messages by identifier.
# Fix: treat @lid values in SenderAlt as opaque device IDs, fall back to the
# JID-derived phone_number for source_id and identifier.
# ===========================================================================
  if defined?(Whatsapp::EvolutionGoHandlers::MessagesUpsert)
    Whatsapp::EvolutionGoHandlers::MessagesUpsert.module_eval do
      private

      def determine_source_id(sender_alt_value, phone_number)
        if sender_alt_value.present? && !sender_alt_value.to_s.include?('@lid')
          Rails.logger.info "Evolution Go API [RXP] Using SenderAlt '#{sender_alt_value}' as source_id (JID)"
          sender_alt_value
        else
          Rails.logger.info "Evolution Go API [RXP] SenderAlt is LID or blank -- using phone_number '#{phone_number}' as source_id"
          phone_number
        end
      end

      def build_contact_attributes(push_name, phone_number, sender_alt_value, is_whatsapp_number)
        attributes = { name: push_name }
        # Only use SenderAlt as identifier when it is a JID, not a LID
        if sender_alt_value.present? && !sender_alt_value.to_s.include?('@lid')
          attributes[:identifier] = sender_alt_value
        end
        attributes[:phone_number] = "+#{phone_number}" if is_whatsapp_number
        attributes
      end

      def update_contact_information(push_name, phone_number, sender_alt_value, is_whatsapp_number)
        updates = {}
        updates[:name] = push_name if @contact.name == phone_number && push_name.present?

        jid_alt = sender_alt_value.present? && !sender_alt_value.to_s.include?('@lid')
        if @contact.identifier.blank? && jid_alt
          updates[:identifier] = sender_alt_value
          Rails.logger.info "Evolution Go API [RXP]: Adding identifier #{sender_alt_value} to contact #{@contact.id}"
        end

        if @contact.phone_number.blank? && is_whatsapp_number
          updates[:phone_number] = "+#{phone_number}"
          Rails.logger.info "Evolution Go API [RXP]: Adding phone_number +#{phone_number} to contact #{@contact.id}"
        end

        @contact.update!(updates) if updates.any?
      end
    end
    Rails.logger.info '[RXP_PATCH] EvolutionGoHandlers::MessagesUpsert -- LID source_id fix (bug 24)'
  end

# ===========================================================================
# Bug 25 (v2) -- PipelineItemsController#index N+1: stage_movements + contact
# ---------------------------------------------------------------------------
# PipelineItem has TWO entity paths:
#   - conversation-based: pipeline_item.conversation.contact (most items)
#   - lead-based:         pipeline_item.contact (direct contact_id, no conversation)
# v1 patch only preloaded contact inside conversation includes -- lead-based
# items still fired 1 SQL per item.
#
# days_in_current_stage calls stage_movements.order(:created_at).last which
# adds ORDER BY and creates a NEW query scope even when stage_movements is
# preloaded -- bypassing the batch include entirely.
#
# Fix A: add { contact: { avatar_attachment: :blob } } at top level so
#        lead-based items get batch-loaded too.
# Fix B: patch PipelineItem#days_in_current_stage to sort in-memory when
#        the association is already loaded.
# ===========================================================================
  if defined?(Api::V1::PipelineItemsController)
    Api::V1::PipelineItemsController.prepend(Module.new do
      def index
        contact_includes = [:labels, { avatar_attachment: :blob }]
        @pipeline_items = @pipeline.pipeline_items.includes(
          :pipeline_stage,
          :stage_movements,
          { contact: contact_includes },
          conversation: [
            :assignee,
            :team,
            { contact: contact_includes },
            { messages: [:attachments, { sender: { avatar_attachment: :blob } }] }
          ]
        )
        apply_filters
        apply_sorting
        labels_by_title = Label.all.index_by(&:title)
        Thread.current[:rxp_labels_by_title] = labels_by_title
        begin
          success_response(
            data: PipelineItemSerializer.serialize_collection(
              @pipeline_items,
              include_entity: true,
              include_labels: true,
              labels_by_title: labels_by_title
            ),
            message: 'Pipeline items retrieved successfully'
          )
        ensure
          Thread.current[:rxp_labels_by_title] = nil
        end
      end
    end)
    Rails.logger.info '[RXP_PATCH] PipelineItemsController#index -- N+1 fix v3 labels+lead-contact (bug 25)'
  end

  if defined?(ContactSerializer)
    # rc6 upgrade (2026-07-06): rc6 upstream adicionou ContactPiiMasker no bloco
    # de #serialize (ContactSerializer#serialize agora chama ContactPiiMasker.should_mask?).
    # Nosso prepend chama super() que executa o corpo rc6. Se ContactPiiMasker
    # nao estiver definido (feature flag off ou classe missing), super levanta
    # NameError e explode nossos endpoints de pipeline_items#index.
    # Guarda: rescue NameError -> loga warning e retorna hash minimal
    # (id/name apenas) pra evitar 500. Melhor degradar do que quebrar UI.
    ContactSerializer.singleton_class.prepend(Module.new do
      def serialize(contact, include_labels: true, **options)
        result = begin
          super(contact, include_labels: false, **options)
        rescue NameError => e
          unless Thread.current[:rxp_pii_masker_warned]
            Rails.logger.warn "[RXP_PATCH][bug25b] ContactSerializer super raised NameError: #{e.message}. Falling back to minimal hash."
            Thread.current[:rxp_pii_masker_warned] = true
          end
          { 'id' => contact.id, 'name' => contact.name, 'type' => contact.try(:type) }.compact
        end
        if include_labels && result.is_a?(Hash)
          labels_by_title = Thread.current[:rxp_labels_by_title]
          result['labels'] = contact.labels.map do |tag|
            lbl = labels_by_title ? labels_by_title[tag.name] : Label.find_by(title: tag.name)
            { name: tag.name, color: lbl&.color || '#1f93ff' }
          end
        end
        result
      end
    end)
    Rails.logger.info '[RXP_PATCH] ContactSerializer -- labels_by_title thread-local (no Label.find_by per tag) (bug 25, rc6-safe)'
  end

  if defined?(PipelineItem)
    PipelineItem.prepend(Module.new do
      def days_in_current_stage
        last_movement = if association(:stage_movements).loaded?
                          stage_movements.max_by(&:created_at)
                        else
                          stage_movements.order(:created_at).last
                        end
        start_time = last_movement&.created_at || entered_at
        ((Time.current - start_time) / 1.day).round
      end
    end)
    Rails.logger.info '[RXP_PATCH] PipelineItem#days_in_current_stage -- in-memory sort when preloaded (bug 25)'
  end

  # ===========================================================================
  # Bug 26 (v2 -- fix definitivo) -- Aurora MESSAGES_UPDATE: raw_message_id
  # usava :messageId (ID interno do Prisma do evo.xmacna.ai) em vez de :keyId
  # (wamid real = source_id no CRM).
  #
  # Fluxo do evento messages.update recebido do Evolution API v2 (Cloud API):
  #   data.messageId = "cmqs7ozt705cepl01mlhe3z42"  <- Prisma ID (inutil aqui)
  #   data.keyId     = "wamid.HBgM..."              <- wamid = source_id do CRM
  #
  # Com a prioridade errada (:messageId primeiro), find_message_by_source_id
  # nunca encontrava a mensagem e logava "Message not found for update: cmqs7..."
  # O evento chegava ao CRM mas era descartado silenciosamente.
  #
  # Fix: inverter prioridade -- :keyId primeiro, :messageId como fallback.
  # Seguro: para messages.upsert, nenhum dos dois existe e o fallback
  # @raw_message.dig(:key, :id) continua funcionando normalmente.
  #
  # Verificacao: payload de teste em 2026-06-30 confirmou que apos o fix
  # o evento chega, o lookup por keyId encontra a mensagem e o status atualiza.
  # ===========================================================================
  if defined?(Whatsapp::EvolutionHandlers::Helpers)
    Whatsapp::EvolutionHandlers::Helpers.module_eval do
      unless private_method_defined?(:raw_message_id_without_keyid_fix)
        alias_method :raw_message_id_without_keyid_fix, :raw_message_id
        def raw_message_id
          @raw_message[:keyId] || @raw_message[:messageId] || @raw_message.dig(:key, :id)
        end
      end
    end
    Rails.logger.info '[RXP_PATCH] Bug 26 v2 -- EvolutionHandlers#raw_message_id keyId>messageId fix (MESSAGES_UPDATE aurora)'
  end

end

# ===========================================================================
# Bug 27 -- Filtro de conversas perdido ao paginar (scroll infinito)
# Root cause: loadMoreConversations sempre chama GET /conversations?page=N
# sem os filtros ativos, mesmo quando a carga inicial foi feita via
# POST /conversations/filter. Resultado: página 2+ traz conversas sem filtro.
#
# Fix (frontend JS — /opt/evocrm-patches/assets/ChatPage-BV93Mg_x.js):
#   1. filterConversations() armazena o corpo do filtro em window._rxpFilterBody
#   2. getConversations() quando page>1 e _rxpFilterBody presente redireciona
#      para POST /conversations/filter com page, garantindo filtro preservado.
#   3. _rxpFilterBody é limpo quando page===1 (nova busca sem filtro).
#
# Patch aplicado em: /opt/evocrm-patches/assets/ChatPage-BV93Mg_x.js
# Backup em: ChatPage-BV93Mg_x.js.bak-bug27
# ===========================================================================

# ===========================================================================
# Bug 28 (v2) -- WebhookListener nao recebe eventos Wisper contact_created/contact_updated
# ---------------------------------------------------------------------------
# Root cause: upstream comentou dispatch_update_event em app/models/contact.rb:78
# ("Disabled - using Wisper events instead") mas nao registrou o WebhookListener
# como subscriber global do bus Wisper. Resultado: publish(:contact_created) e
# publish(:contact_updated) nunca chegam ao WebhookListener#contact_created/updated,
# WebhookJob nunca eh enfileirado, POST para os webhooks account_type nao ocorre.
#
# Impacto observado: workflow n8n RXP_TAG_SYNC_CRM_MAUTIC (1M3eijJjn9HKYawS)
# com 0 execucoes apesar de webhook 30c7f8bb valido no banco.
#
# Fix design: WebhookListener foi projetado pro AsyncDispatcher (event objects
# Events::Base com .data). Wisper entrega Hash bruto {data: {...}}. Solucao:
# adapter subscriber que converte Hash -> Events::Base e delega ao
# WebhookListener singleton. Nao pode subscribir WebhookListener direto
# (quebra com "undefined method 'data' for an instance of Hash").
# Guard duplo: (a) evo_flow_style guard (return if data.respond_to?(:data))
# alinhado com EvoFlow::ContactEventsListener; (b) nil-check contact/account
# antes de delegar.
# ===========================================================================
module RxpPatches
  class WebhookListenerWisperAdapter
    def contact_created(data)
      # Se ja for event object (AsyncDispatcher), ignora - AsyncDispatcher ja rota WebhookListener
      return if data.respond_to?(:data)
      dispatch_to_webhook_listener(:contact_created, data)
    end

    def contact_updated(data)
      return if data.respond_to?(:data)
      dispatch_to_webhook_listener(:contact_updated, data)
    end

    private

    def dispatch_to_webhook_listener(event_name, data)
      event_data = data.is_a?(Hash) ? (data[:data] || data) : nil
      return log_missing(event_name, 'event_data') unless event_data.is_a?(Hash)
      return log_missing(event_name, 'contact') unless event_data[:contact]

      event_obj = Events::Base.new(event_name.to_s, Time.zone.now, event_data)
      WebhookListener.instance.public_send(event_name, event_obj)
    rescue StandardError => e
      Rails.logger.error "[RXP_PATCH][bug28] WebhookListenerWisperAdapter##{event_name} failed: #{e.class}: #{e.message}"
      Sentry.capture_exception(e) if defined?(Sentry)
      nil
    end

    def log_missing(event_name, key)
      Rails.logger.warn "[RXP_PATCH][bug28] WebhookListenerWisperAdapter##{event_name}: #{key} missing/invalid"
      nil
    end
  end
end

Rails.application.config.after_initialize do
  if defined?(WebhookListener) && defined?(Wisper) && defined?(Events::Base)
    Wisper.subscribe(RxpPatches::WebhookListenerWisperAdapter.new)
    Rails.logger.info '[RXP_PATCH] WebhookListenerWisperAdapter registered on Wisper bus (bug 28)'
  else
    Rails.logger.warn '[RXP_PATCH] Bug 28 skipped: WebhookListener/Wisper/Events::Base not all defined'
  end
end
