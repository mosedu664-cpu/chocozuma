/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { Component, onMounted, useRef } from "@odoo/owl";
import { markEventHandled } from '@web/core/utils/misc';
import { sprintf } from '@web/core/utils/strings';
import { EventBus, whenReady } from "@odoo/owl";
import { Attachment } from "@mail/core/common/attachment_model";
import { AttachmentList, ImageActions } from "@mail/core/common/attachment_list"
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";

var extensions = ['pdf', 'PDF', 'zpl', 'ZPL', 'png', 'PNG', 'jpg', 'JPG']

patch(AttachmentList.prototype, {
  setup() {
    super.setup(...arguments);
    this.attachment = true;
    this._onClickPrint = this._onClickPrint.bind(this);
    this.notif = useService("notification"); 
    this.companyService = useService("company");
  },

  getActions(attachment){
    let res = super.getActions(attachment);
    res.push({
      label: "Print Direct",
      icon: "fa fa-print",
      onSelect: () => this._onClickPrint(attachment),
    });
    return res
  },

  canPrint(attachment) {
    return extensions.includes(attachment.extension)
  },

  async _onClickPrint(attachment) {
    let activeCompanyIds = this.companyService.activeCompanyIds;
    let id = attachment.id
    if(extensions.includes(attachment.extension)){
        const result = await rpc("/direct-print/attachment-info", { id });
        if (result.success) {
            this.notif.add("Print job created successfully.", { type: "success" });
        } else {
            alert(result.msg)
        }
    }else{
        console.log('FILE TYPE NOT SUPPORTED FOR PRINTING.')
    }
  },
});
